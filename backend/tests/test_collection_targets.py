import pytest

from app.schemas import CollectionTargetCreateRequest, CollectionTargetUpdateRequest, OpportunityInput
from app.services import collection_targets as collection_targets_module
from app.services.collection_targets import (
    create_collection_target,
    get_collection_target,
    list_collection_checks,
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
