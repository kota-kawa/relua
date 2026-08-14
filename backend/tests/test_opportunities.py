from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from app.dates import today_in_tokyo
from app.models import PUBLIC_CODE_ALPHABET, PUBLIC_CODE_LENGTH, Company, Opportunity
from app.schemas import OpportunityInput
from app.services.opportunities import (
    DomainValidationError,
    find_similar_opportunities,
    get_opportunity_by_public_ref,
    search_opportunities,
    write_opportunity,
)
from tests.test_validation import valid_payload


def test_create_search_and_idempotent_replay(db):
    data = OpportunityInput.model_validate(valid_payload())
    created, replayed = write_opportunity(
        db,
        data=data,
        request_id="test-request-0001",
        client_name="pytest",
    )
    assert replayed is False

    replay, replayed = write_opportunity(
        db,
        data=data,
        request_id="test-request-0001",
        client_name="pytest",
    )
    assert replayed is True
    assert replay.id == created.id

    result = search_opportunities(db, q="テスト", industry=["industry-01"])
    assert result.total == 1
    assert result.items[0].company.name == "株式会社テスト"
    assert search_opportunities(db, degree=["degree-01"]).total == 1
    assert search_opportunities(db, degree=["degree-06"]).total == 0


def test_public_listing_cutoff_excludes_expired_deadlines_but_keeps_undated(db):
    today = date(2026, 8, 14)
    for index, deadline in enumerate((today - timedelta(days=1), today, None), start=1):
        payload = valid_payload() | {
            "company_name": f"株式会社締切テスト{index}",
            "event_name": f"締切テスト{index}",
            "deadline": deadline.isoformat() if deadline else None,
            "source_url": f"https://example.com/deadline-{index}",
        }
        write_opportunity(
            db,
            data=OpportunityInput.model_validate(payload),
            request_id=f"deadline-filter-{index:04d}",
            client_name="pytest",
        )

    public_result = search_opportunities(db, deadline_on_or_after=today)
    assert public_result.total == 2
    assert {item.deadline for item in public_result.items} == {today, None}

    # Operator searches still need to find expired records so their status can be maintained.
    assert search_opportunities(db).total == 3


def test_today_in_tokyo_changes_at_tokyo_midnight():
    assert today_in_tokyo(datetime(2026, 8, 13, 14, 59, tzinfo=timezone.utc)) == date(2026, 8, 13)  # noqa: UP017
    assert today_in_tokyo(datetime(2026, 8, 13, 15, 0, tzinfo=timezone.utc)) == date(2026, 8, 14)  # noqa: UP017


def test_company_normalization_reuses_existing_company(db):
    first = OpportunityInput.model_validate(valid_payload())
    first_item, _ = write_opportunity(db, data=first, request_id="normalize-0001", client_name="pytest")

    second_payload = valid_payload() | {"company_name": "(株)テスト", "event_name": "別の募集"}
    second = OpportunityInput.model_validate(second_payload)
    second_item, _ = write_opportunity(db, data=second, request_id="normalize-0002", client_name="pytest")
    assert first_item.company_id == second_item.company_id
    assert second_item.company.name == "株式会社テスト"


def test_same_company_suggestions_can_be_limited_to_current_openings(db):
    today = date.today()
    current, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload() | {"event_name": "本選考"}),
        request_id="related-current-0001",
        client_name="pytest",
    )
    open_item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": "(株)テスト",
                "event_name": "サマーインターン",
                "source_url": "https://example.com/related-open",
            }
        ),
        request_id="related-open-0001",
        client_name="pytest",
    )
    closed_item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "event_name": "終了済み説明会",
                "deadline": (today - timedelta(days=1)).isoformat(),
                "source_url": "https://example.com/related-closed",
            }
        ),
        request_id="related-closed-0001",
        client_name="pytest",
    )

    matches = find_similar_opportunities(
        db,
        company_name="株式会社テスト",
        exclude_id=current.id,
        recruitment_statuses=["募集予定", "募集中", "通年募集"],
        deadline_on_or_after=today,
        limit=3,
    )

    assert [item.id for item in matches] == [open_item.id]
    assert closed_item.id not in {item.id for item in matches}


def test_sector_must_belong_to_industry(db):
    payload = valid_payload() | {"sector": "銀行"}
    data = OpportunityInput.model_validate(payload)
    try:
        write_opportunity(db, data=data, request_id="invalid-sector-01", client_name="pytest")
    except DomainValidationError as exc:
        assert exc.errors[0]["field"] == "業種"
    else:
        raise AssertionError("DomainValidationError was not raised")


def test_ai_sector_can_be_used_under_it_industry(db):
    payload = valid_payload() | {"sector": "AI", "event_name": "AI開発インターン"}
    data = OpportunityInput.model_validate(payload)
    item, replayed = write_opportunity(db, data=data, request_id="ai-sector-0001", client_name="pytest")

    assert replayed is False
    assert item.industry.name == "IT・通信"
    assert item.sector.name == "AI"
    assert item.sector.slug == "sector-1-71"


def test_child_sector_refines_only_its_selected_parent(db):
    ai_payload = valid_payload() | {"sector": "AI", "event_name": "AI開発インターン"}
    write_opportunity(
        db,
        data=OpportunityInput.model_validate(ai_payload),
        request_id="hierarchy-ai-0001",
        client_name="pytest",
    )
    finance_payload = valid_payload() | {
        "company_name": "株式会社金融テスト",
        "industry": "金融",
        "sector": "銀行",
        "event_name": "金融インターン",
    }
    write_opportunity(
        db,
        data=OpportunityInput.model_validate(finance_payload),
        request_id="hierarchy-finance-0001",
        client_name="pytest",
    )

    result = search_opportunities(
        db,
        industry=["industry-01", "industry-04"],
        sector=["sector-1-71"],
    )
    assert {item.event_name for item in result.items} == {"AI開発インターン", "金融インターン"}


def test_new_opportunity_gets_a_distinct_short_public_code(db):
    first, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload()),
        request_id="public-code-0001",
        client_name="pytest",
    )
    second_payload = valid_payload() | {"event_name": "二件目の募集"}
    second, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(second_payload),
        request_id="public-code-0002",
        client_name="pytest",
    )

    assert len(first.public_code) == PUBLIC_CODE_LENGTH
    assert set(first.public_code) <= set(PUBLIC_CODE_ALPHABET)
    assert first.public_code != second.public_code


def test_read_path_resolves_both_the_public_code_and_the_uuid(db):
    item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload()),
        request_id="public-ref-0001",
        client_name="pytest",
    )

    assert get_opportunity_by_public_ref(db, item.public_code).id == item.id
    assert get_opportunity_by_public_ref(db, item.public_code.lower()).id == item.id
    assert get_opportunity_by_public_ref(db, item.id).id == item.id
    assert get_opportunity_by_public_ref(db, "ZZZZZZZZ") is None


def test_database_rejects_invalid_date_relationship(db):
    company = Company(name="株式会社DB制約テスト", normalized_name="db制約テスト")
    db.add(company)
    db.flush()
    with pytest.raises(IntegrityError):
        db.execute(
            insert(Opportunity).values(
                id="db-constraint-test",
                status_id=2,
                company_id=company.id,
                industry_id=1,
                sector_id=1,
                event_type_id=1,
                event_format_id=2,
                event_name="不正な日付",
                description="終了日が開始日より前です。",
                event_start_date=date(2026, 9, 2),
                event_end_date=date(2026, 9, 1),
                source_url="https://example.com/source",
            )
        )
