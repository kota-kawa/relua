import pytest
from sqlalchemy import select

from app.models import AuditLog, Company, CompanyAlias, CompanyRequestRecord
from app.schemas import OpportunityInput
from app.services.companies import (
    CompanyIdentityValidationError,
    add_company_alias,
    company_keyword_filter,
    delete_company_alias,
    get_or_create_company,
    resolve_company_candidates,
)
from app.services.opportunities import search_opportunities, write_opportunity
from tests.test_validation import valid_payload


def company(db, name: str):
    item = get_or_create_company(db, name)
    db.flush()
    return item


def test_resolve_company_returns_exact_partial_and_fuzzy_matches(db):
    dena = company(db, "株式会社ディー・エヌ・エー")

    canonical = resolve_company_candidates(db, "ディーエヌエー")
    assert canonical[0].company.id == dena.id
    assert canonical[0].match_type == "canonical_exact"

    partial = resolve_company_candidates(db, "ディーエヌ")
    assert partial[0].company.id == dena.id
    assert partial[0].match_type == "partial"

    fuzzy = resolve_company_candidates(db, "ディーエヌエア")
    assert fuzzy[0].company.id == dena.id
    assert fuzzy[0].match_type == "fuzzy"
    assert fuzzy[0].score >= 0.8


def test_add_company_alias_is_audited_idempotent_and_used_for_resolution(db):
    dena = company(db, "株式会社ディー・エヌ・エー")

    resolved, changed, replayed = add_company_alias(
        db,
        company_id=dena.id,
        alias="DeNA",
        request_id="company-alias-add-0001",
        client_name="pytest",
    )
    assert resolved.id == dena.id
    assert changed is True
    assert replayed is False
    assert resolve_company_candidates(db, "dena")[0].match_type == "alias_exact"

    replay, changed, replayed = add_company_alias(
        db,
        company_id=dena.id,
        alias="dena",
        request_id="company-alias-add-0001",
        client_name="pytest",
    )
    assert replay.id == dena.id
    assert changed is False
    assert replayed is True
    assert len(list(db.scalars(select(CompanyAlias)))) == 1
    assert len(list(db.scalars(select(CompanyRequestRecord)))) == 1

    audit = db.scalar(select(AuditLog).where(AuditLog.action == "company_alias_add"))
    assert audit is not None
    assert audit.entity_type == "company"
    assert audit.changes["after"]["aliases"][0]["alias"] == "DeNA"


def test_add_company_alias_rejects_canonical_and_alias_collisions(db):
    dena = company(db, "株式会社ディー・エヌ・エー")
    other = company(db, "株式会社別企業")

    with pytest.raises(CompanyIdentityValidationError, match="validation_failed") as canonical:
        add_company_alias(
            db,
            company_id=other.id,
            alias="ディーエヌエー",
            request_id="company-alias-conflict-0001",
            client_name="pytest",
        )
    assert "正式名" in canonical.value.errors[0]["reason"]

    add_company_alias(
        db,
        company_id=dena.id,
        alias="DeNA",
        request_id="company-alias-conflict-0002",
        client_name="pytest",
    )
    with pytest.raises(CompanyIdentityValidationError, match="validation_failed") as alias:
        add_company_alias(
            db,
            company_id=other.id,
            alias="ＤｅＮＡ",
            request_id="company-alias-conflict-0003",
            client_name="pytest",
        )
    assert "別名として登録済み" in alias.value.errors[0]["reason"]


def test_company_alias_request_id_cannot_be_reused_for_another_operation(db):
    dena = company(db, "株式会社ディー・エヌ・エー")
    add_company_alias(
        db,
        company_id=dena.id,
        alias="DeNA",
        request_id="company-alias-reuse-0001",
        client_name="pytest",
    )

    with pytest.raises(CompanyIdentityValidationError) as exc:
        add_company_alias(
            db,
            company_id=dena.id,
            alias="Mobage",
            request_id="company-alias-reuse-0001",
            client_name="pytest",
        )
    assert exc.value.errors[0]["field"] == "request_id"


def test_delete_company_alias_is_idempotent_and_stops_exact_resolution(db):
    dena = company(db, "株式会社ディー・エヌ・エー")
    company_with_alias, _, _ = add_company_alias(
        db,
        company_id=dena.id,
        alias="DeNA",
        request_id="company-alias-delete-setup",
        client_name="pytest",
    )
    alias_id = company_with_alias.aliases[0].id

    result, replayed = delete_company_alias(
        db,
        alias_id=alias_id,
        request_id="company-alias-delete-0001",
        client_name="pytest",
    )
    assert result.id == dena.id
    assert replayed is False
    assert resolve_company_candidates(db, "DeNA") == []

    replay, replayed = delete_company_alias(
        db,
        alias_id=alias_id,
        request_id="company-alias-delete-0001",
        client_name="pytest",
    )
    assert replay.id == dena.id
    assert replayed is True


def test_postgresql_opportunity_search_recovers_a_typo_in_a_normalized_alias(db):
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("pg_trgm is PostgreSQL-specific")
    item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload() | {"company_name": "株式会社ディー・エヌ・エー"}
        ),
        request_id="company-alias-search-setup",
        client_name="pytest",
    )
    add_company_alias(
        db,
        company_id=item.company_id,
        alias="DeNA",
        request_id="company-alias-search-add",
        client_name="pytest",
    )

    result = search_opportunities(db, q="DeNAA")

    assert [match.id for match in result.items] == [item.id]
    companies = list(db.scalars(select(Company).where(company_keyword_filter(db, "DeNAA"))))
    assert [company.id for company in companies] == [item.company_id]
