import pytest
from sqlalchemy import select

from app.models import (
    AuditLog,
    CollectionCheck,
    CollectionSource,
    CollectionTarget,
    Company,
    CompanyAlias,
    CompanyIndustry,
    CompanyRequestRecord,
    Industry,
    Opportunity,
)
from app.schemas import OpportunityInput
from app.services.companies import (
    CompanyIdentityValidationError,
    add_company_alias,
    company_keyword_filter,
    delete_company_alias,
    get_or_create_company,
    merge_company,
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


def test_merge_company_moves_references_keeps_old_names_and_is_idempotent(db):
    source = company(db, "株式会社旧ティス")
    target = company(db, "TIS株式会社")
    _, _, _ = add_company_alias(
        db, company_id=source.id, alias="旧TIS", request_id="company-merge-source-alias", client_name="pytest"
    )
    add_company_alias(
        db, company_id=target.id, alias="TIS", request_id="company-merge-target-alias", client_name="pytest"
    )
    it = db.scalar(select(Industry).where(Industry.name == "IT・通信"))
    finance = db.scalar(select(Industry).where(Industry.name == "金融"))
    assert it is not None and finance is not None
    db.add_all(
        [
            CompanyIndustry(company_id=source.id, industry_id=it.id, is_primary=True),
            CompanyIndustry(company_id=target.id, industry_id=finance.id, is_primary=True),
        ]
    )
    source_target = CollectionTarget(company_id=source.id, priority_tier=1, check_interval_days=7, is_active=True)
    target_target = CollectionTarget(company_id=target.id, priority_tier=2, check_interval_days=30, is_active=False)
    db.add_all([source_target, target_target])
    db.flush()
    db.add_all(
        [
            CollectionSource(collection_target_id=source_target.id, source_type="recruit", url="https://example.com/old"),
            CollectionSource(collection_target_id=source_target.id, source_type="event", url="https://example.com/shared"),
            CollectionSource(collection_target_id=target_target.id, source_type="event", url="https://example.com/shared"),
            CollectionCheck(
                collection_target_id=source_target.id,
                result="no_opening",
                request_id="company-merge-check-0001",
                client_name="pytest",
            ),
        ]
    )
    old_opportunity, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload() | {"company_name": source.name, "source_url": "https://example.com/old-posting"}
        ),
        request_id="company-merge-old-opportunity",
        client_name="pytest",
    )

    merged, summary, replayed = merge_company(
        db,
        source_company_id=source.id,
        target_company_id=target.id,
        request_id="company-merge-0001",
        client_name="pytest",
    )

    assert replayed is False
    assert merged.id == target.id
    assert db.get(Company, source.id) is None
    assert db.get(Opportunity, old_opportunity.id).company_id == target.id
    assert {alias.normalized_alias for alias in merged.aliases} >= {"旧ティス", "旧tis"}
    assert summary["opportunities_moved"] == 1
    assert summary["aliases_moved"] == 2  # Old canonical name and its existing alias.
    assert summary["industries_moved"] == 1
    assert summary["collection_targets_merged"] == 1
    assert summary["collection_sources_moved"] == 1
    assert summary["collection_sources_deduplicated"] == 1
    # One explicit no-opening check plus the found check auto-recorded with the opportunity write.
    assert summary["collection_checks_moved"] == 2
    assert db.scalar(select(CollectionTarget).where(CollectionTarget.company_id == source.id)) is None
    retained_target = db.scalar(select(CollectionTarget).where(CollectionTarget.company_id == target.id))
    assert retained_target is not None
    assert retained_target.priority_tier == 1
    assert retained_target.is_active is True
    assert len(list(db.scalars(select(CollectionCheck).where(CollectionCheck.collection_target_id == retained_target.id)))) == 2
    assert len(list(db.scalars(select(CollectionSource).where(CollectionSource.collection_target_id == retained_target.id)))) == 2
    assert db.scalar(select(CompanyRequestRecord).where(CompanyRequestRecord.request_id == "company-merge-source-alias")).company_id == target.id
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "company_merge"))
    assert audit is not None
    assert audit.changes["before"]["source_company"]["id"] == source.id

    replay, replay_summary, replayed = merge_company(
        db,
        source_company_id=source.id,
        target_company_id=target.id,
        request_id="company-merge-0001",
        client_name="pytest",
    )
    assert replayed is True
    assert replay.id == target.id
    assert replay_summary == summary
