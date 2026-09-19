import pytest
from sqlalchemy import select

from app.models import (
    PUBLIC_CODE_ALPHABET,
    PUBLIC_CODE_LENGTH,
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
    company_identity_dict,
    company_keyword_filter,
    delete_company_alias,
    get_company_by_public_code,
    get_or_create_company,
    merge_company,
    resolve_company_candidates,
    update_company_profile,
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


def test_company_keyword_filter_treats_percent_and_underscore_as_literal_characters(db):
    """Without escaping, ilike("%%%%%") - the pattern a query of a bare "%" builds - matches every
    row and gets reported to the caller as a keyword hit, and a bare "_" matches any single
    character; neither pattern can use an index either. company_keyword_filter must treat both as
    literal text to search for, not as SQL LIKE wildcards."""
    company(db, "株式会社ワイルドカード保護")
    company(db, "有限会社パーセント検索")

    assert list(db.scalars(select(Company).where(company_keyword_filter(db, "%")))) == []
    assert list(db.scalars(select(Company).where(company_keyword_filter(db, "_")))) == []


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


def test_new_company_gets_a_unique_resolvable_public_code(db):
    first = company(db, "株式会社アルファ")
    second = company(db, "株式会社ベータ")

    for item in (first, second):
        assert len(item.public_code) == PUBLIC_CODE_LENGTH
        assert set(item.public_code) <= set(PUBLIC_CODE_ALPHABET)
    assert first.public_code != second.public_code

    assert get_company_by_public_code(db, first.public_code).id == first.id
    # A hand-typed lowercase URL still resolves; the page then redirects to the canonical casing.
    assert get_company_by_public_code(db, first.public_code.lower()).id == first.id
    assert get_company_by_public_code(db, "TOOLONGCODE") is None


#: The service is given values the input schema already length-checked, so these only need to be
#: distinguishable. The enforced minimums are covered by the schema tests in test_mcp_tools.py.
GAMMA_PROFILE = {
    "business_summary": "産業用センサーを設計・製造し、国内の製造業へ販売している。",
    "description": "自社工場でセンサーを設計から製造まで手がけ、制御ソフトウェアと組み合わせて提供しています。",
    "business_areas": [
        {"name": "センサー事業", "description": "工場設備向けの各種センサーを開発・製造しています。"},
        {"name": "ソフトウェア事業", "description": "センサーの計測データを可視化する制御ソフトウェアを提供しています。"},
    ],
    "website_url": "https://gamma.example.com/",
}


def test_update_company_profile_is_audited_idempotent_and_records_the_confirmed_page(db):
    target = company(db, "株式会社ガンマ")

    updated, changed, replayed = update_company_profile(
        db,
        company_id=target.id,
        changes=dict(GAMMA_PROFILE),
        source_url="https://gamma.example.com/company/",
        request_id="company-profile-0001",
        client_name="pytest",
    )
    assert (changed, replayed) == (True, False)
    assert updated.business_summary == GAMMA_PROFILE["business_summary"]
    assert updated.description == GAMMA_PROFILE["description"]
    assert [area["name"] for area in updated.business_areas] == ["センサー事業", "ソフトウェア事業"]
    assert updated.website_url == "https://gamma.example.com/"

    replay, changed_again, replayed_again = update_company_profile(
        db,
        company_id=target.id,
        changes=dict(GAMMA_PROFILE),
        source_url="https://gamma.example.com/company/",
        request_id="company-profile-0001",
        client_name="pytest",
    )
    assert (replay.id, changed_again, replayed_again) == (target.id, False, True)
    assert len(list(db.scalars(select(CompanyRequestRecord)))) == 1

    audit = db.scalar(select(AuditLog).where(AuditLog.action == "company_profile_update"))
    assert audit.entity_type == "company"
    assert audit.entity_id == str(target.id)
    # The page the text was confirmed on is evidence, kept in the log rather than on the row.
    assert audit.source_url == "https://gamma.example.com/company/"
    assert audit.changes["before"]["business_summary"] is None
    assert audit.changes["before"]["business_areas"] == []
    assert audit.changes["after"]["business_summary"] == GAMMA_PROFILE["business_summary"]
    assert len(audit.changes["after"]["business_areas"]) == 2

    # The profile travels with every company response, so resolve_company shows it too.
    identity = company_identity_dict(updated)
    assert identity["business_summary"] == GAMMA_PROFILE["business_summary"]
    assert identity["business_areas"][0]["name"] == "センサー事業"


def test_company_profile_business_areas_are_replaced_as_a_whole_set(db):
    target = company(db, "株式会社シータ")
    update_company_profile(
        db,
        company_id=target.id,
        changes={"business_areas": GAMMA_PROFILE["business_areas"]},
        source_url="https://theta.example.com/company/",
        request_id="company-profile-theta-1",
        client_name="pytest",
    )

    replaced, changed, _ = update_company_profile(
        db,
        company_id=target.id,
        changes={"business_areas": [{"name": "計測受託事業", "description": "設備の計測と分析を受託しています。"}]},
        source_url="https://theta.example.com/company/",
        request_id="company-profile-theta-2",
        client_name="pytest",
    )
    assert changed is True
    assert [area["name"] for area in replaced.business_areas] == ["計測受託事業"]

    cleared, changed, _ = update_company_profile(
        db,
        company_id=target.id,
        changes={"business_areas": None},
        source_url="https://theta.example.com/company/",
        request_id="company-profile-theta-3",
        client_name="pytest",
    )
    assert changed is True
    assert cleared.business_areas is None
    assert company_identity_dict(cleared)["business_areas"] == []


def test_company_profile_patch_keeps_omitted_fields_and_clears_explicit_nulls(db):
    target = company(db, "株式会社デルタ")
    update_company_profile(
        db,
        company_id=target.id,
        changes={
            "business_summary": "物流倉庫の自動化システムを提供している。",
            "description": "倉庫内の搬送機器と管理システムを組み合わせて納入しています。",
            "website_url": "https://delta.example.com/",
        },
        source_url="https://delta.example.com/about/",
        request_id="company-profile-delta-1",
        client_name="pytest",
    )

    # Only description is sent, so the summary and the website must survive untouched.
    updated, changed, _ = update_company_profile(
        db,
        company_id=target.id,
        changes={"description": "倉庫と工場の搬送機器、管理システム、保守サービスを提供しています。"},
        source_url="https://delta.example.com/about/",
        request_id="company-profile-delta-2",
        client_name="pytest",
    )
    assert changed is True
    assert updated.description == "倉庫と工場の搬送機器、管理システム、保守サービスを提供しています。"
    assert updated.business_summary == "物流倉庫の自動化システムを提供している。"
    assert updated.website_url == "https://delta.example.com/"

    cleared, changed, _ = update_company_profile(
        db,
        company_id=target.id,
        changes={"description": None},
        source_url="https://delta.example.com/about/",
        request_id="company-profile-delta-3",
        client_name="pytest",
    )
    assert changed is True
    assert cleared.description is None
    assert cleared.website_url == "https://delta.example.com/"

    # Re-sending the same clear is a real no-op rather than a replay of a stored result.
    unchanged, changed, replayed = update_company_profile(
        db,
        company_id=target.id,
        changes={"description": None},
        source_url="https://delta.example.com/about/",
        request_id="company-profile-delta-4",
        client_name="pytest",
    )
    assert (changed, replayed) == (False, False)
    assert unchanged.description is None


def test_company_profile_request_id_cannot_be_reused_for_another_change(db):
    target = company(db, "株式会社イプシロン")
    update_company_profile(
        db,
        company_id=target.id,
        changes={"description": "半導体検査装置を製造する。"},
        source_url="https://epsilon.example.com/company/",
        request_id="company-profile-epsilon",
        client_name="pytest",
    )

    with pytest.raises(CompanyIdentityValidationError) as error:
        update_company_profile(
            db,
            company_id=target.id,
            changes={"description": "別の内容に差し替える。"},
            source_url="https://epsilon.example.com/company/",
            request_id="company-profile-epsilon",
            client_name="pytest",
        )
    assert error.value.errors[0]["field"] == "request_id"


def test_update_company_profile_rejects_unknown_fields_and_missing_companies(db):
    target = company(db, "株式会社ゼータ")
    with pytest.raises(CompanyIdentityValidationError):
        update_company_profile(
            db,
            company_id=target.id,
            changes={"name": "改名"},
            source_url="https://zeta.example.com/company/",
            request_id="company-profile-zeta-1",
            client_name="pytest",
        )
    with pytest.raises(LookupError):
        update_company_profile(
            db,
            company_id=target.id + 9999,
            changes={"description": "存在しない企業。"},
            source_url="https://zeta.example.com/company/",
            request_id="company-profile-zeta-2",
            client_name="pytest",
        )


def test_merge_company_keeps_the_target_profile_and_inherits_only_missing_fields(db):
    source = company(db, "株式会社旧イータ")
    target = company(db, "イータ株式会社")
    update_company_profile(
        db,
        company_id=source.id,
        changes={
            "business_summary": "統合元が持つ一言説明。",
            "description": "統合元が持つ説明。",
            "website_url": "https://old-eta.example.com/",
        },
        source_url="https://old-eta.example.com/company/",
        request_id="company-merge-profile-source",
        client_name="pytest",
    )
    # The target has its own description but no website: only the gap should be filled.
    update_company_profile(
        db,
        company_id=target.id,
        changes={"business_summary": "統合先が確認済みの一言説明。", "description": "統合先が確認済みの説明。"},
        source_url="https://eta.example.com/company/",
        request_id="company-merge-profile-target",
        client_name="pytest",
    )

    merged, _, _ = merge_company(
        db,
        source_company_id=source.id,
        target_company_id=target.id,
        request_id="company-merge-profile-0001",
        client_name="pytest",
    )

    assert merged.business_summary == "統合先が確認済みの一言説明。"
    assert merged.description == "統合先が確認済みの説明。"
    assert merged.website_url == "https://old-eta.example.com/"
