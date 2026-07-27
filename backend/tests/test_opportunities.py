from datetime import date

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from app.models import Company, Opportunity
from app.schemas import OpportunityInput
from app.services.opportunities import DomainValidationError, search_opportunities, write_opportunity
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


def test_company_normalization_reuses_existing_company(db):
    first = OpportunityInput.model_validate(valid_payload())
    first_item, _ = write_opportunity(db, data=first, request_id="normalize-0001", client_name="pytest")

    second_payload = valid_payload() | {"company_name": "(株)テスト", "event_name": "別の募集"}
    second = OpportunityInput.model_validate(second_payload)
    second_item, _ = write_opportunity(db, data=second, request_id="normalize-0002", client_name="pytest")
    assert first_item.company_id == second_item.company_id
    assert second_item.company.name == "株式会社テスト"


def test_sector_must_belong_to_industry(db):
    payload = valid_payload() | {"sector": "銀行"}
    data = OpportunityInput.model_validate(payload)
    try:
        write_opportunity(db, data=data, request_id="invalid-sector-01", client_name="pytest")
    except DomainValidationError as exc:
        assert exc.errors[0]["field"] == "業種"
    else:
        raise AssertionError("DomainValidationError was not raised")


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
