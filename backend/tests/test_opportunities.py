from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from app.dates import today_in_tokyo
from app.models import PUBLIC_CODE_ALPHABET, PUBLIC_CODE_LENGTH, Company, CompanyAlias, Opportunity
from app.schemas import OpportunityInput
from app.services.normalization import normalize_company_name
from app.services.opportunities import (
    DomainValidationError,
    find_similar_opportunities,
    get_opportunity_by_public_ref,
    list_stale_opportunities,
    search_opportunities,
    update_recruitment_status,
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


def test_keyword_search_defaults_to_weighted_relevance(db):
    query = "データサイエンティスト"
    payloads = [
        valid_payload()
        | {
            "company_name": f"株式会社{query}",
            "event_name": "会社説明会",
            "description": "事業内容を紹介します。",
            "job_categories": ["営業"],
            "source_url": "https://example.com/relevance-company",
        },
        valid_payload()
        | {
            "company_name": "株式会社イベント検索",
            "event_name": f"{query}インターン",
            "description": "仕事を体験します。",
            "job_categories": ["営業"],
            "source_url": "https://example.com/relevance-event",
        },
        valid_payload()
        | {
            "company_name": "株式会社職種検索",
            "event_name": "専門職インターン",
            "description": "実務を体験します。",
            "job_categories": [query],
            "source_url": "https://example.com/relevance-job",
        },
        valid_payload()
        | {
            "company_name": "株式会社説明検索",
            "event_name": "技術系インターン",
            "description": f"{query}の実務を体験します。",
            "job_categories": ["営業"],
            "source_url": "https://example.com/relevance-description",
        },
    ]
    for index, payload in enumerate(payloads):
        write_opportunity(
            db,
            data=OpportunityInput.model_validate(payload),
            request_id=f"relevance-ranking-{index:04d}",
            client_name="pytest",
        )

    result = search_opportunities(db, q=query)

    assert [item.company.name for item in result.items] == [
        f"株式会社{query}",
        "株式会社イベント検索",
        "株式会社職種検索",
        "株式会社説明検索",
    ]


def test_explicit_deadline_sort_overrides_relevance(db):
    query = "機械学習"
    later, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": f"株式会社{query}",
                "event_name": f"{query}エンジニア選考",
                "description": f"{query}の仕事です。",
                "deadline": (date.today() + timedelta(days=20)).isoformat(),
                "source_url": "https://example.com/relevance-later",
            }
        ),
        request_id="relevance-deadline-later",
        client_name="pytest",
    )
    sooner, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": "株式会社締切優先",
                "event_name": f"{query}講座",
                "deadline": (date.today() + timedelta(days=2)).isoformat(),
                "source_url": "https://example.com/relevance-sooner",
            }
        ),
        request_id="relevance-deadline-sooner",
        client_name="pytest",
    )

    assert search_opportunities(db, q=query).items[0].id == later.id
    assert search_opportunities(db, q=query, sort="deadline").items[0].id == sooner.id


def test_relevance_cursor_does_not_skip_tied_scores(db):
    query = "検索順位"
    created = []
    for index in range(3):
        item, _ = write_opportunity(
            db,
            data=OpportunityInput.model_validate(
                valid_payload()
                | {
                    "company_name": f"株式会社カーソル{index}",
                    "event_name": f"{query}インターン",
                    "description": "同じ内容です。",
                    "job_categories": ["営業"],
                    "source_url": f"https://example.com/relevance-cursor-{index}",
                }
            ),
            request_id=f"relevance-cursor-{index:04d}",
            client_name="pytest",
        )
        created.append(item.id)

    seen = []
    cursor = None
    while True:
        result = search_opportunities(db, q=query, page=None, per_page=1, cursor=cursor)
        seen.extend(item.id for item in result.items)
        cursor = result.next_cursor
        if cursor is None:
            break

    assert len(seen) == 3
    assert set(seen) == set(created)


def test_postgresql_trigram_search_recovers_a_typo(db):
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("pg_trgm is PostgreSQL-specific")
    item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": "株式会社類似検索",
                "event_name": "ソフトウェアエンジニア選考",
                "description": "開発職の募集です。",
                "source_url": "https://example.com/relevance-typo",
            }
        ),
        request_id="relevance-typo-0001",
        client_name="pytest",
    )

    result = search_opportunities(db, q="ソフトウェアエンジニヤ")

    assert [match.id for match in result.items] == [item.id]


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


def test_company_normalization_collapses_nakaguro_spelling(db):
    """"ディー・エヌ・エー" and "ディーエヌエー" differ only by a syllable separator, so they must
    resolve to one company - not the different script "DeNA", which needs an alias instead."""
    first_payload = valid_payload() | {"company_name": "株式会社ディー・エヌ・エー"}
    first = OpportunityInput.model_validate(first_payload)
    first_item, _ = write_opportunity(db, data=first, request_id="nakaguro-0001", client_name="pytest")

    second_payload = valid_payload() | {"company_name": "ディーエヌエー", "event_name": "別の募集"}
    second = OpportunityInput.model_validate(second_payload)
    second_item, _ = write_opportunity(db, data=second, request_id="nakaguro-0002", client_name="pytest")

    assert first_item.company_id == second_item.company_id
    assert search_opportunities(db, q="ディーエヌエー").total == 2
    matches = find_similar_opportunities(db, company_name="ディーエヌエー")
    assert {item.id for item in matches} == {first_item.id, second_item.id}


def test_company_alias_resolves_search_relevance_and_duplicates(db):
    dena_payload = valid_payload() | {"company_name": "株式会社ディー・エヌ・エー"}
    dena = OpportunityInput.model_validate(dena_payload)
    dena_item, _ = write_opportunity(db, data=dena, request_id="alias-0001", client_name="pytest")
    db.add(
        CompanyAlias(
            company_id=dena_item.company_id, alias="DeNA", normalized_alias=normalize_company_name("DeNA")
        )
    )
    db.flush()

    result = search_opportunities(db, q="DeNA")
    assert result.total == 1
    assert result.items[0].company.name == "株式会社ディー・エヌ・エー"

    matches = find_similar_opportunities(db, company_name="DeNA")
    assert [item.id for item in matches] == [dena_item.id]

    # Writing under the alias must reuse the existing company rather than creating a duplicate one,
    # otherwise the same DeNA opening would silently end up split across two Company rows.
    reused_payload = valid_payload() | {
        "company_name": "DeNA",
        "event_name": "別の募集",
        "source_url": "https://example.com/alias-reuse",
    }
    reused = OpportunityInput.model_validate(reused_payload)
    reused_item, _ = write_opportunity(db, data=reused, request_id="alias-0002", client_name="pytest")
    assert reused_item.company_id == dena_item.company_id


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


@pytest.mark.parametrize("industry", ["メーカー", "商社"])
def test_sonota_sector_resolves_to_its_own_industrys_row(db, industry):
    """Regression test: every industry seeds its own "その他" sector row with the same name.

    Resolution must be scoped by industry, or a caller can be told by get_sectors that "その他" is a
    valid choice for their industry, then have add_opportunity reject that exact pair because sector
    resolution silently picked a different industry's "その他" row of the same name.
    """
    from app.services.masters import sectors_for_industry

    _, sectors = sectors_for_industry(db, industry)
    expected_sector = next(item for item in sectors if item.name == "その他")

    payload = valid_payload() | {
        "industry": industry,
        "sector": "その他",
        "event_name": f"{industry}その他インターン",
        "source_url": f"https://example.com/{industry}-sonota",
    }
    data = OpportunityInput.model_validate(payload)
    item, replayed = write_opportunity(db, data=data, request_id=f"sonota-{industry}-0001", client_name="pytest")

    assert replayed is False
    assert item.industry.name == industry
    assert item.sector.name == "その他"
    assert item.sector.id == expected_sector.id
    assert item.sector.industry_id == item.industry.id


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


def test_write_opportunity_records_when_the_official_source_was_confirmed(db):
    data = OpportunityInput.model_validate(valid_payload())
    item, _ = write_opportunity(db, data=data, request_id="checked-at-0001", client_name="pytest")

    assert item.source_checked_at is not None
    assert item.source_checked_at == item.updated_at


def test_write_opportunity_locks_company_before_checking_duplicates(db):
    """write_opportunity now resolves+row-locks the Company before find_exact_duplicates runs
    (previously the duplicate check ran first, so two concurrent writers for the same company could
    both pass it before either committed). This asserts the reordering didn't change the outcome for
    a single writer: the second write for the same company+event is still rejected as a duplicate.

    A true concurrent-race assertion needs two live DB connections (e.g. Postgres, two threads/
    sessions), which this in-process SQLite fixture cannot exercise - out of scope here.
    """
    data = OpportunityInput.model_validate(valid_payload())
    write_opportunity(db, data=data, request_id="lock-order-0001", client_name="pytest")

    with pytest.raises(DomainValidationError) as exc_info:
        write_opportunity(
            db,
            data=OpportunityInput.model_validate(valid_payload() | {"source_url": "https://example.com/source-2"}),
            request_id="lock-order-0002",
            client_name="pytest",
        )
    assert exc_info.value.errors[0]["field"] == "イベント名"
    assert exc_info.value.errors[0]["existing"]


def test_update_recruitment_status_also_refreshes_source_checked_at(db):
    data = OpportunityInput.model_validate(valid_payload())
    item, _ = write_opportunity(db, data=data, request_id="checked-at-status-0001", client_name="pytest")
    first_checked_at = item.source_checked_at

    updated, _ = update_recruitment_status(
        db,
        opportunity_id=item.id,
        recruitment_status="締切",
        request_id="checked-at-status-0002",
        client_name="pytest",
    )

    assert updated.source_checked_at is not None
    assert updated.source_checked_at >= first_checked_at
    assert updated.source_checked_at == updated.updated_at


def test_list_stale_opportunities_prioritizes_never_checked_then_oldest_first(db):
    fresh, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload() | {"company_name": "株式会社新しい確認", "source_url": "https://example.com/stale-fresh"}
        ),
        request_id="stale-fresh-0001",
        client_name="pytest",
    )
    stale, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload() | {"company_name": "株式会社古い確認", "source_url": "https://example.com/stale-old"}
        ),
        request_id="stale-old-0001",
        client_name="pytest",
    )
    stale.source_checked_at = datetime.now(timezone.utc) - timedelta(days=40)  # noqa: UP017 -- local Python is 3.10
    never_checked, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload() | {"company_name": "株式会社未確認", "source_url": "https://example.com/stale-never"}
        ),
        request_id="stale-never-0001",
        client_name="pytest",
    )
    never_checked.source_checked_at = None
    db.commit()

    assert search_opportunities(db, q="株式会社新しい確認").total == 1  # sanity: fresh really was written
    stale_results = list_stale_opportunities(db, days=7)
    stale_ids = [item.id for item in stale_results]

    assert fresh.id not in stale_ids
    assert stale_ids.index(never_checked.id) < stale_ids.index(stale.id)
