import pytest

from app.schemas import (
    CollectionCheckRequest,
    CollectionTargetCreateRequest,
    CollectionTargetUpdateRequest,
    OpportunityInput,
)
from app.services import collection_targets as collection_targets_module
from app.services.collection_targets import (
    collection_target_dict,
    create_collection_target,
    get_collection_target,
    list_collection_checks,
    record_collection_check,
    undercovered_collection_targets,
    update_collection_target,
)
from app.services.opportunities import DomainValidationError, write_opportunity
from tests.test_validation import valid_payload


def target_payload(**overrides) -> CollectionTargetCreateRequest:
    payload = {
        "company_name": "株式会社収集キューテスト",
        "industry": "IT・通信",
        "sector": "Webサービス",
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
                "request_id": "confirm-only-check-0001",
                "client_name": "pytest",
            }
        ),
    )

    assert item.source_checked_at is not None
    assert item.source_checked_at > original_checked_at
    assert item.updated_at == original_updated_at


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
    assert target.industry.name == "メーカー"
    assert target.sector.name == "その他"
    assert target.sector.industry_id == target.industry.id


def test_collection_target_id_mismatch_reports_company_and_industry_separately(db):
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

    with pytest.raises(DomainValidationError) as industry_exc:
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
    reason = industry_exc.value.errors[0]["reason"]
    assert "IT・通信" in reason
    assert "メーカー" in reason


def test_collection_target_dict_distinguishes_company_wide_from_target_linked_counts(db):
    target, _ = create_collection_target(
        db,
        target_payload(
            company_name="株式会社カウント検証",
            industry="IT・通信",
            sources=[{"source_type": "recruit", "url": "https://example.com/count-check"}],
            request_id="count-check-target-0001",
        ),
    )

    # A posting for the same company under a DIFFERENT industry: counts company-wide, but does not
    # auto-link to this target (which is scoped to IT・通信).
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
    assert snapshot["target_linked_opportunity_count"] == 0

    # A posting under the target's own industry links to it.
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
    assert snapshot["target_linked_opportunity_count"] == 1


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

    record_collection_check(
        db,
        target_id=target.id,
        payload=CollectionCheckRequest.model_validate(
            {"result": result, "request_id": f"status-check-{result}-0001", "client_name": "pytest"}
        ),
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
