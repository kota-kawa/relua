import pytest

from app.schemas import (
    CollectionCheckRequest,
    CollectionSourceUpdateRequest,
    CollectionTargetCreateRequest,
    CollectionTargetUpdateRequest,
    OpportunityInput,
)
from app.services import collection_targets as collection_targets_module
from app.services.collection_targets import (
    collection_target_dict,
    create_collection_target,
    get_collection_target,
    get_company_maintenance_context,
    list_collection_checks,
    list_collection_targets,
    list_unmonitored_companies,
    record_collection_check,
    undercovered_collection_targets,
    update_collection_source,
    update_collection_target,
)
from app.services.company_industries import company_industries
from app.services.opportunities import DomainValidationError, write_opportunity
from tests.test_validation import valid_payload


def target_payload(**overrides) -> CollectionTargetCreateRequest:
    """Build a create request, letting a test say industry="メーカー" instead of spelling out the list."""

    industry = overrides.pop("industry", "IT・通信")
    sector = overrides.pop("sector", "Webサービス")
    payload = {
        "company_name": "株式会社収集キューテスト",
        "industries": [{"industry": industry, "sector": sector}],
        "priority_tier": 1,
        "check_interval_days": 14,
        "selection_reason": "確認対象",
        "sources": [{"source_type": "recruit", "url": "https://example.com/recruit"}],
        "request_id": "collection-queue-test-0001",
        "client_name": "pytest",
    }
    return CollectionTargetCreateRequest.model_validate(payload | overrides)


def test_tier_one_creation_is_capped(db, monkeypatch):
    monkeypatch.setattr(collection_targets_module, "PRIORITY_TIER_1_CAP", 2)

    for index in range(2):
        create_collection_target(
            db,
            target_payload(
                company_name=f"株式会社キャップ{index}",
                sources=[{"source_type": "recruit", "url": f"https://example.com/cap/{index}"}],
                request_id=f"cap-create-{index:04d}",
            ),
        )

    with pytest.raises(DomainValidationError) as exc:
        create_collection_target(
            db,
            target_payload(
                company_name="株式会社キャップ超過",
                sources=[{"source_type": "recruit", "url": "https://example.com/cap/overflow"}],
                request_id="cap-create-overflow",
            ),
        )
    assert exc.value.errors[0]["field"] == "priority_tier"

    # Tier 2 is unaffected by the tier-1 cap.
    created, _ = create_collection_target(
        db,
        target_payload(
            company_name="株式会社キャップtier2",
            priority_tier=2,
            sources=[{"source_type": "recruit", "url": "https://example.com/cap/tier2"}],
            request_id="cap-create-tier2",
        ),
    )
    assert created.priority_tier == 2


def test_tier_one_promotion_via_update_is_capped(db, monkeypatch):
    monkeypatch.setattr(collection_targets_module, "PRIORITY_TIER_1_CAP", 1)

    create_collection_target(
        db,
        target_payload(
            company_name="株式会社既存tier1",
            sources=[{"source_type": "recruit", "url": "https://example.com/existing"}],
            request_id="cap-update-existing",
        ),
    )
    tier_two, _ = create_collection_target(
        db,
        target_payload(
            company_name="株式会社昇格対象",
            priority_tier=2,
            sources=[{"source_type": "recruit", "url": "https://example.com/promote"}],
            request_id="cap-update-tier2",
        ),
    )

    with pytest.raises(DomainValidationError) as exc:
        update_collection_target(
            db,
            target_id=tier_two.id,
            payload=CollectionTargetUpdateRequest.model_validate(
                {"priority_tier": 1, "request_id": "cap-update-promote", "client_name": "pytest"}
            ),
        )
    assert exc.value.errors[0]["field"] == "priority_tier"

    # Re-saving the already-tier-1 target (no tier/is_active change) must not be blocked by its own count.
    update_collection_target(
        db,
        target_id=tier_two.id,
        payload=CollectionTargetUpdateRequest.model_validate(
            {"selection_reason": "更新", "request_id": "cap-update-untouched", "client_name": "pytest"}
        ),
    )


def test_opportunity_write_auto_links_a_matching_collection_target_without_an_id(db):
    target, _ = create_collection_target(
        db,
        target_payload(
            company_name="株式会社自動紐付け",
            sources=[{"source_type": "recruit", "url": "https://example.com/auto-link"}],
            request_id="auto-link-target-0001",
        ),
    )
    assert target.last_checked_at is None

    data = OpportunityInput.model_validate(
        valid_payload() | {"company_name": "株式会社自動紐付け", "source_url": "https://example.com/auto-link-posting"}
    )
    item, _ = write_opportunity(db, data=data, request_id="auto-link-write-0001", client_name="pytest")

    refreshed = get_collection_target(db, target.id)
    assert refreshed.last_checked_at is not None
    assert refreshed.last_check_result == "found"
    checks = list_collection_checks(db, target_id=target.id)
    assert checks[0].opportunity_id == item.id


def test_existing_company_id_can_be_added_to_collection_and_unmonitored_companies_are_listed(db):
    monitored, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload() | {"company_name": "Salesforce", "source_url": "https://example.com/salesforce-posting"}
        ),
        request_id="existing-company-target-salesforce",
        client_name="pytest",
    )
    unmonitored, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": "Adobe",
                "event_name": "Adobe向けインターン",
                "source_url": "https://example.com/adobe-posting",
            }
        ),
        request_id="existing-company-target-adobe",
        client_name="pytest",
    )
    target, replayed = create_collection_target(
        db,
        target_payload(
            company_name=None,
            company_id=monitored.company_id,
            request_id="existing-company-target-create",
            sources=[{"source_type": "recruit", "url": "https://example.com/salesforce-careers"}],
        ),
    )
    missing = list_unmonitored_companies(db, query="Adobe")

    assert replayed is False
    assert target.company_id == monitored.company_id
    assert [item.company.id for item in missing.items] == [unmonitored.company_id]
    assert missing.items[0].opportunity_count == 1
    assert list_unmonitored_companies(db, industry="IT・通信").total == 1


def test_collection_target_create_requires_exactly_one_company_reference():
    with pytest.raises(ValueError, match="どちらか一方"):
        target_payload(company_id=1)
    with pytest.raises(ValueError, match="どちらか一方"):
        target_payload(company_name=None)


def test_confirm_only_check_refreshes_source_checked_at_without_touching_updated_at(db):
    target, _ = create_collection_target(
        db,
        target_payload(
            company_name="株式会社確認のみ",
            sources=[{"source_type": "recruit", "url": "https://example.com/confirm-only"}],
            request_id="confirm-only-target-0001",
        ),
    )
    data = OpportunityInput.model_validate(
        valid_payload() | {"company_name": "株式会社確認のみ", "source_url": "https://example.com/confirm-only-posting"}
    )
    item, _ = write_opportunity(db, data=data, request_id="confirm-only-write-0001", client_name="pytest")
    original_updated_at = item.updated_at
    original_checked_at = item.source_checked_at

    # No fields changed - the agent just reconfirmed the same posting is still up, which is exactly
    # the case write_opportunity never sees and previously left source_checked_at stale forever.
    record_collection_check(
        db,
        target_id=target.id,
        payload=CollectionCheckRequest.model_validate(
            {
                "result": "found",
                "opportunity_id": item.id,
                "source_url": item.source_url,
                "request_id": "confirm-only-check-0001",
                "client_name": "pytest",
            }
        ),
    )

    assert item.source_checked_at is not None
    assert item.source_checked_at > original_checked_at
    assert item.updated_at == original_updated_at


def test_found_check_requires_the_opportunity_source_url(db):
    target, _ = create_collection_target(
        db,
        target_payload(
            company_name="株式会社確認URL照合",
            sources=[{"source_type": "recruit", "url": "https://example.com/check-source"}],
            request_id="check-source-target-0001",
        ),
    )
    item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": "株式会社確認URL照合",
                "source_url": "https://example.com/check-source/posting",
            }
        ),
        request_id="check-source-write-0001",
        client_name="pytest",
    )
    original_checked_at = item.source_checked_at

    with pytest.raises(DomainValidationError) as exc_info:
        record_collection_check(
            db,
            target_id=target.id,
            payload=CollectionCheckRequest.model_validate(
                {
                    "result": "found",
                    "opportunity_id": item.id,
                    "source_url": "https://example.com/check-source/other",
                    "request_id": "check-source-mismatch-0001",
                    "client_name": "pytest",
                }
            ),
        )

    assert exc_info.value.errors[0]["field"] == "source_url"
    assert item.source_checked_at == original_checked_at


def test_non_found_check_requires_an_active_registered_source_url(db):
    target, _ = create_collection_target(
        db,
        target_payload(
            company_name="株式会社確認元限定",
            sources=[{"source_type": "recruit", "url": "https://example.com/registered"}],
            request_id="registered-check-target-0001",
        ),
    )

    with pytest.raises(DomainValidationError) as exc_info:
        record_collection_check(
            db,
            target_id=target.id,
            payload=CollectionCheckRequest.model_validate(
                {
                    "result": "no_opening",
                    "source_url": "https://unknown.example/unchecked",
                    "request_id": "registered-check-mismatch-0001",
                    "client_name": "pytest",
                }
            ),
        )

    assert "登録済み" in exc_info.value.errors[0]["reason"]


def test_record_collection_check_rejects_reusing_a_write_opportunitys_request_id(db):
    """write_opportunity records its own CollectionCheck (see _record_collection_success) without
    ever creating a CollectionRequestRecord for it, so _replayed_entity_id cannot see that row.
    record_collection_check must still notice the collision itself and return the same structured
    "reused request_id" error every other collision on this id gets, instead of letting the insert
    hit collection_checks.request_id's UNIQUE constraint as a raw IntegrityError (a 500)."""
    target, _ = create_collection_target(
        db,
        target_payload(
            company_name="株式会社確認ID衝突",
            sources=[{"source_type": "recruit", "url": "https://example.com/request-id-collision"}],
            request_id="request-id-collision-target-0001",
        ),
    )
    item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": "株式会社確認ID衝突",
                "source_url": "https://example.com/request-id-collision/posting",
            }
        ),
        request_id="request-id-collision-write-0001",
        client_name="pytest",
    )

    with pytest.raises(DomainValidationError) as exc_info:
        record_collection_check(
            db,
            target_id=target.id,
            payload=CollectionCheckRequest.model_validate(
                {
                    "result": "found",
                    "opportunity_id": item.id,
                    "source_url": item.source_url,
                    "request_id": "request-id-collision-write-0001",
                    "client_name": "pytest",
                }
            ),
        )

    assert exc_info.value.errors[0]["field"] == "request_id"


def test_opportunity_source_must_match_the_company_official_allowlist(db):
    target, _ = create_collection_target(
        db,
        target_payload(
            company_name="株式会社公式ドメイン限定",
            sources=[{"source_type": "recruit", "url": "https://careers.example.com/"}],
            request_id="source-allowlist-target-0001",
        ),
    )

    with pytest.raises(DomainValidationError) as exc_info:
        write_opportunity(
            db,
            data=OpportunityInput.model_validate(
                valid_payload()
                | {
                    "company_name": "株式会社公式ドメイン限定",
                    "source_url": "https://unknown-job-board.example/posting",
                }
            ),
            request_id="source-allowlist-write-0001",
            client_name="pytest",
            collection_target_id=target.id,
        )

    assert "allowlist" in exc_info.value.errors[0]["reason"]


def test_collection_target_sonota_sector_resolves_to_its_own_industrys_row(db):
    target, _ = create_collection_target(
        db,
        target_payload(
            company_name="株式会社メーカーその他収集",
            industry="メーカー",
            sector="その他",
            sources=[{"source_type": "recruit", "url": "https://example.com/maker-sonota"}],
            request_id="maker-sonota-target-0001",
        ),
    )
    classification = company_industries(db, target.company_id)[0]
    assert classification.industry.name == "メーカー"
    assert classification.sector.name == "その他"
    assert classification.sector.industry_id == classification.industry_id


def test_collection_target_id_rejects_a_different_company_but_accepts_a_different_industry(db):
    target, _ = create_collection_target(
        db,
        target_payload(
            company_name="株式会社紐付け照合",
            industry="IT・通信",
            sources=[{"source_type": "recruit", "url": "https://example.com/link-check"}],
            request_id="link-check-target-0001",
        ),
    )

    with pytest.raises(DomainValidationError) as company_exc:
        write_opportunity(
            db,
            data=OpportunityInput.model_validate(
                valid_payload() | {"company_name": "株式会社別の企業", "source_url": "https://example.com/link-check-company"}
            ),
            request_id="link-check-company-0001",
            client_name="pytest",
            collection_target_id=target.id,
        )
    reason = company_exc.value.errors[0]["reason"]
    assert "株式会社紐付け照合" in reason
    assert "株式会社別の企業" in reason

    # A target covers the whole company, so a posting under one of the company's other industries is
    # a normal write - and it teaches the company that industry instead of being rejected.
    write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": "株式会社紐付け照合",
                "industry": "メーカー",
                "sector": "電機・精密",
                "source_url": "https://example.com/link-check-industry",
            }
        ),
        request_id="link-check-industry-0001",
        client_name="pytest",
        collection_target_id=target.id,
    )
    snapshot = collection_target_dict(db, get_collection_target(db, target.id))
    assert [
        (entry["industry"]["name"], entry["sector"]["name"], entry["is_primary"])
        for entry in snapshot["industries"]
    ] == [("IT・通信", "Webサービス", True), ("メーカー", "電機・精密", False)]
    assert snapshot["primary_industry"]["name"] == "IT・通信"


def test_one_company_spanning_two_industries_is_a_single_target(db):
    """The Ubie case: one company, two industries, and exactly one row to check and to count."""

    target, _ = create_collection_target(
        db,
        target_payload(
            company_name="Ubie株式会社",
            industries=[
                {"industry": "IT・通信", "sector": "AI"},
                {"industry": "医療・製薬", "sector": "ヘルスケア"},
            ],
            sources=[{"source_type": "recruit", "url": "https://ubie.example.com/recruit"}],
            request_id="multi-industry-target-0001",
        ),
    )

    snapshot = collection_target_dict(db, get_collection_target(db, target.id))
    assert [entry["industry"]["name"] for entry in snapshot["industries"]] == ["IT・通信", "医療・製薬"]
    assert snapshot["primary_industry"]["name"] == "IT・通信"

    # Reachable from either industry, still one row - the count of targets is the count of companies.
    for industry in ("IT・通信", "医療・製薬"):
        result = list_collection_targets(db, industry=industry, query="Ubie")
        assert [item.id for item in result.items] == [target.id]
        assert result.total == 1

    with pytest.raises(DomainValidationError) as exc:
        create_collection_target(
            db,
            target_payload(
                company_name="Ubie株式会社",
                industry="医療・製薬",
                sector="ヘルスケア",
                sources=[{"source_type": "recruit", "url": "https://ubie.example.com/recruit-2"}],
                request_id="multi-industry-target-0002",
            ),
        )
    assert exc.value.errors[0]["reason"] == "この企業の収集対象が既に存在します"
    assert f"target_id={target.id}" in exc.value.errors[0]["alternative"]


def test_updating_industries_replaces_the_whole_classification(db):
    target, _ = create_collection_target(
        db,
        target_payload(
            company_name="株式会社分類差し替え",
            industries=[
                {"industry": "IT・通信", "sector": "Webサービス"},
                {"industry": "メーカー", "sector": "電機・精密"},
            ],
            request_id="reclassify-target-0001",
        ),
    )

    update_collection_target(
        db,
        target_id=target.id,
        payload=CollectionTargetUpdateRequest.model_validate(
            {
                "industries": [{"industry": "メーカー", "sector": "機械"}],
                "request_id": "reclassify-target-0002",
                "client_name": "pytest",
            }
        ),
    )

    snapshot = collection_target_dict(db, get_collection_target(db, target.id))
    assert [
        (entry["industry"]["name"], entry["sector"]["name"], entry["is_primary"])
        for entry in snapshot["industries"]
    ] == [("メーカー", "機械", True)]
    assert list_collection_targets(db, industry="IT・通信", query="分類差し替え").total == 0


def test_company_wide_postings_all_count_toward_one_target(db):
    target, _ = create_collection_target(
        db,
        target_payload(
            company_name="株式会社カウント検証",
            industry="IT・通信",
            sources=[{"source_type": "recruit", "url": "https://example.com/count-check"}],
            request_id="count-check-target-0001",
        ),
    )

    # A posting for the same company under a different industry. It used to belong to a second
    # target and left this one reading as uncovered; now it counts here and adds a classification.
    write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": "株式会社カウント検証",
                "industry": "メーカー",
                "sector": "電機・精密",
                "source_url": "https://example.com/count-check-other-industry",
            }
        ),
        request_id="count-check-write-0001",
        client_name="pytest",
    )
    snapshot = collection_target_dict(db, get_collection_target(db, target.id))
    assert snapshot["company_opportunity_count"] == 1
    assert [entry["industry"]["name"] for entry in snapshot["industries"]] == ["IT・通信", "メーカー"]

    write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": "株式会社カウント検証",
                "event_name": "別イベント",
                "source_url": "https://example.com/count-check-own-industry",
            }
        ),
        request_id="count-check-write-0002",
        client_name="pytest",
    )
    snapshot = collection_target_dict(db, get_collection_target(db, target.id))
    assert snapshot["company_opportunity_count"] == 2


def test_collection_maintenance_views_exclude_closed_postings(db):
    target, _ = create_collection_target(
        db,
        target_payload(
            company_name="株式会社終了除外",
            sources=[{"source_type": "recruit", "url": "https://example.com/closed-filter-target"}],
            request_id="closed-filter-target-0001",
        ),
    )
    active, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": "株式会社終了除外",
                "event_name": "現行募集",
                "source_url": "https://example.com/closed-filter-active",
            }
        ),
        request_id="closed-filter-active-0001",
        client_name="pytest",
    )
    closed, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "recruitment_status": "締切",
                "company_name": "株式会社終了除外",
                "event_name": "終了募集",
                "source_url": "https://example.com/closed-filter-closed",
            }
        ),
        request_id="closed-filter-closed-0001",
        client_name="pytest",
    )

    snapshot = collection_target_dict(db, get_collection_target(db, target.id))
    assert [item["id"] for item in snapshot["opportunities"]] == [active.id]
    assert snapshot["company_opportunity_count"] == 1

    context = get_company_maintenance_context(db, active.company_id)
    assert context is not None
    assert [item.id for item in context[2]] == [active.id]
    assert closed.id not in {item.id for item in context[2]}


@pytest.mark.parametrize(
    ("result", "expected_status"),
    [
        ("found", "found"),
        ("no_opening", "no_active_opportunity"),
        ("unreachable", "source_unavailable"),
        ("needs_review", "needs_review"),
    ],
)
def test_check_status_maps_last_check_result(db, result, expected_status):
    target, _ = create_collection_target(
        db,
        target_payload(
            company_name=f"株式会社ステータス{result}",
            sources=[{"source_type": "recruit", "url": f"https://example.com/status-{result}"}],
            request_id=f"status-target-{result}-0001",
        ),
    )
    assert collection_target_dict(db, target)["check_status"] == "unreviewed"

    check_payload = {
        "result": result,
        "source_url": f"https://example.com/status-{result}",
        "request_id": f"status-check-{result}-0001",
        "client_name": "pytest",
    }
    if result == "found":
        opportunity, _ = write_opportunity(
            db,
            data=OpportunityInput.model_validate(
                valid_payload()
                | {
                    "company_name": f"株式会社ステータス{result}",
                    "source_url": f"https://example.com/status-{result}",
                }
            ),
            request_id=f"status-opportunity-{result}-0001",
            client_name="pytest",
        )
        check_payload["opportunity_id"] = opportunity.id

    record_collection_check(
        db,
        target_id=target.id,
        payload=CollectionCheckRequest.model_validate(check_payload),
    )
    refreshed = get_collection_target(db, target.id)
    assert collection_target_dict(db, refreshed)["check_status"] == expected_status


def test_undercovered_collection_targets_orders_by_ascending_linked_opportunities(db):
    targets = {}
    for index in range(3):
        target, _ = create_collection_target(
            db,
            target_payload(
                company_name=f"株式会社未充足{index}",
                sources=[{"source_type": "recruit", "url": f"https://example.com/undercovered/{index}"}],
                request_id=f"undercovered-target-{index:04d}",
            ),
        )
        targets[index] = target

    # index 0 -> 0 opportunities, index 1 -> 1, index 2 -> 2
    for index in (1, 2):
        for count in range(index):
            write_opportunity(
                db,
                data=OpportunityInput.model_validate(
                    valid_payload()
                    | {
                        "company_name": f"株式会社未充足{index}",
                        "event_name": f"募集{count}",
                        "source_url": f"https://example.com/undercovered/{index}/posting/{count}",
                    }
                ),
                request_id=f"undercovered-write-{index}-{count}",
                client_name="pytest",
            )

    ordered = undercovered_collection_targets(db, industry="IT・通信", limit=10)
    ordered_ids = [item.id for item in ordered]
    assert ordered_ids.index(targets[0].id) < ordered_ids.index(targets[1].id) < ordered_ids.index(targets[2].id)


def test_top_page_only_target_is_reported_and_filterable_as_a_source_gap(db):
    top_page_only, _ = create_collection_target(
        db,
        target_payload(
            company_name="株式会社トップページのみ",
            sources=[{"source_type": "other", "url": "https://top-page-only.example.com/"}],
            request_id="collection-source-gap-0001",
        ),
    )
    covered, _ = create_collection_target(
        db,
        target_payload(
            company_name="株式会社採用ページあり",
            sources=[{"source_type": "recruit", "url": "https://covered.example.com/recruit"}],
            request_id="collection-source-gap-0002",
        ),
    )

    gap_view = collection_target_dict(db, top_page_only)
    assert gap_view["has_primary_source"] is False
    assert gap_view["missing_source_types"] == ["recruit", "internship", "event", "news"]

    covered_view = collection_target_dict(db, covered)
    assert covered_view["has_primary_source"] is True
    assert covered_view["missing_source_types"] == ["internship", "event", "news"]

    result = list_collection_targets(db, source_gap=True)
    assert [item.id for item in result.items] == [top_page_only.id]
    assert result.total == 1


def test_deactivated_recruit_page_reopens_the_source_gap(db):
    target, _ = create_collection_target(
        db,
        target_payload(
            company_name="株式会社採用ページ停止",
            sources=[
                {"source_type": "recruit", "url": "https://retired.example.com/recruit"},
                {"source_type": "other", "url": "https://retired.example.com/"},
            ],
            request_id="collection-source-gap-0003",
        ),
    )
    recruit = next(source for source in target.sources if source.source_type == "recruit")
    update_collection_source(
        db,
        source_id=recruit.id,
        payload=CollectionSourceUpdateRequest.model_validate(
            {"is_active": False, "request_id": "collection-source-gap-0004", "client_name": "pytest"}
        ),
    )
    db.refresh(target)

    assert collection_target_dict(db, target)["has_primary_source"] is False
    assert [item.id for item in list_collection_targets(db, source_gap=True).items] == [target.id]


def test_check_can_register_the_recruit_page_it_just_discovered(db):
    target, _ = create_collection_target(
        db,
        target_payload(
            company_name="株式会社採用ページ発見",
            sources=[{"source_type": "other", "url": "https://discovery.example.com/"}],
            request_id="collection-discovery-0001",
        ),
    )

    _, updated, _ = record_collection_check(
        db,
        target_id=target.id,
        payload=CollectionCheckRequest.model_validate(
            {
                "result": "no_opening",
                "source_url": "https://discovery.example.com/",
                "discovered_sources": [
                    {"source_type": "recruit", "url": "https://discovery.example.com/recruit"},
                    {"source_type": "internship", "url": "https://discovery.example.com/internship"},
                    # Already registered: recorded as checked, never added a second time.
                    {"source_type": "other", "url": "https://discovery.example.com/"},
                ],
                "request_id": "collection-discovery-0002",
                "client_name": "pytest",
            }
        ),
    )

    view = collection_target_dict(db, updated)
    # ADR-0013 requires that trusting a new official host be an explicit, separately auditable step,
    # so a page merely mentioned as "discovered" while recording a check lands inactive: it is
    # evidence for review, not yet part of the company's official-source allowlist. It only starts
    # counting toward coverage (and toward add_opportunity's allowlist) once someone reviews it and
    # calls update_collection_source(is_active=True).
    assert [(source["source_type"], source["url"], source["is_active"]) for source in view["sources"]] == [
        ("other", "https://discovery.example.com/", True),
        ("recruit", "https://discovery.example.com/recruit", False),
        ("internship", "https://discovery.example.com/internship", False),
    ]
    assert view["has_primary_source"] is False
    assert view["missing_source_types"] == ["recruit", "internship", "event", "news"]


def test_discovered_sources_do_not_widen_the_official_source_allowlist(db):
    """A source that only ever appeared as check-time discovery must not be usable for writes yet -
    otherwise "found this page while checking" would silently substitute for the explicit
    add_collection_source review ADR-0013 requires before a new host is trusted."""
    # Two different hosts: the registered "other" page stays the only trusted host, and the
    # discovered "recruit" page lives on a host that only its own (inactive) source entry could
    # have vouched for.
    target, _ = create_collection_target(
        db,
        target_payload(
            company_name="株式会社発見元は未許可",
            sources=[{"source_type": "other", "url": "https://corp-guard.example.com/"}],
            request_id="discovery-guard-target-0001",
        ),
    )
    record_collection_check(
        db,
        target_id=target.id,
        payload=CollectionCheckRequest.model_validate(
            {
                "result": "no_opening",
                "source_url": "https://corp-guard.example.com/",
                "discovered_sources": [
                    {"source_type": "recruit", "url": "https://careers-guard.example.com/recruit"},
                ],
                "request_id": "discovery-guard-check-0001",
                "client_name": "pytest",
            }
        ),
    )

    with pytest.raises(DomainValidationError) as exc_info:
        write_opportunity(
            db,
            data=OpportunityInput.model_validate(
                valid_payload()
                | {
                    "company_name": "株式会社発見元は未許可",
                    "source_url": "https://careers-guard.example.com/recruit/posting",
                }
            ),
            request_id="discovery-guard-write-0001",
            client_name="pytest",
        )

    assert "allowlist" in exc_info.value.errors[0]["reason"]
