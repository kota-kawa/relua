"""What an external client such as ChatGPT actually receives from the MCP surface."""

import asyncio
import json
import logging
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app import mcp_server
from app.dates import today_in_tokyo
from app.models import AuditLog, CollectionTarget, Company, CompanyRequestRecord, Industry, Opportunity
from app.schemas import OpportunityInput
from app.services import master_cache
from app.services.errors import FIELD_LABELS
from app.services.opportunities import write_opportunity
from tests.test_validation import valid_payload


@pytest.fixture
def tools(db, monkeypatch):
    """Point the tool layer at the test session.

    The tools open their own sessions through SessionLocal, which no dependency override reaches.
    """

    class Sessions:
        def __call__(self):
            return self

        def __enter__(self):
            return db

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(mcp_server, "SessionLocal", Sessions())
    monkeypatch.setattr(mcp_server, "register_validation_failure", lambda client_name, request_id: 1)
    return mcp_server


def call(name: str, arguments: dict) -> dict:
    """Run a tool the way the transport does, and return its structured content."""
    _, structured = asyncio.run(mcp_server.mcp.call_tool(name, arguments))
    return structured


def tool_error(name: str, arguments: dict) -> dict:
    """The failure payload a client sees. FastMCP prefixes the message, so read the JSON body out of it."""
    with pytest.raises(ToolError) as exc:
        asyncio.run(mcp_server.mcp.call_tool(name, arguments))
    message = str(exc.value)
    return json.loads(message[message.index("{") :])


def seed(db, **overrides):
    payload = valid_payload() | overrides
    request_id = overrides.pop("request_id", None) or f"seed-{payload['event_name']}-0001"
    item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(payload),
        request_id=request_id,
        client_name="pytest",
    )
    return item


def write_args(**overrides) -> dict:
    return {"payload": valid_payload() | {"request_id": "mcp-request-0001"} | overrides}


def test_every_tool_declares_its_title_annotations_and_auth():
    listed = asyncio.run(mcp_server._list_tools_with_security_schemes())
    tools = {tool.name: tool.model_dump(exclude_none=True) for tool in listed}

    assert set(tools) == {
        "search_opportunity",
        "get_opportunity",
        "get_master_values",
        "get_sectors",
        "find_similar_opportunities",
        "find_opportunities_by_source_url",
        "resolve_company",
        "add_company_alias",
        "set_company_industries",
        "update_company_profile",
        "update_company_profiles",
        "delete_company_alias",
        "merge_company",
        "validate_opportunity",
        "add_opportunity",
        "upsert_opportunity",
        "update_opportunity",
        "preview_opportunity_patch",
        "patch_opportunity",
        "update_recruitment_status",
        "verify_opportunity",
        "preview_delete_opportunity",
        "delete_opportunity",
        "restore_opportunity",
        "list_recent_writes",
        "list_stale_opportunities",
        "list_collection_targets",
        "list_unmonitored_companies",
        "list_companies_missing_profile",
        "list_company_profile_history",
        "get_collection_target",
        "get_company_maintenance_context",
        "get_collection_queue",
        "list_undercovered_companies",
        "list_collection_checks",
        "add_collection_target",
        "update_collection_target",
        "add_collection_source",
        "update_collection_source",
        "record_collection_check",
    }
    for name, tool in tools.items():
        assert tool["title"], f"{name} has no title"
        assert tool["annotations"]["openWorldHint"] is False
        assert tool["outputSchema"].get("properties"), f"{name} publishes an empty output schema"
        expected = (
            [{"type": "noauth"}] if name in mcp_server.ANONYMOUS_TOOLS else [{"type": "oauth2", "scopes": ["mcp"]}]
        )
        assert tool["securitySchemes"] == expected

    assert tools["search_opportunity"]["annotations"]["readOnlyHint"] is True
    assert tools["update_opportunity"]["annotations"]["destructiveHint"] is True
    assert tools["add_opportunity"]["annotations"]["destructiveHint"] is False
    assert tools["update_recruitment_status"]["annotations"]["destructiveHint"] is False
    assert tools["verify_opportunity"]["annotations"]["destructiveHint"] is False
    assert tools["verify_opportunity"]["annotations"]["idempotentHint"] is True
    assert tools["delete_opportunity"]["annotations"]["destructiveHint"] is True
    assert tools["delete_opportunity"]["annotations"]["idempotentHint"] is True
    assert tools["delete_opportunity"]["securitySchemes"] == [{"type": "oauth2", "scopes": ["mcp"]}]
    assert tools["preview_delete_opportunity"]["annotations"]["readOnlyHint"] is True
    assert tools["preview_delete_opportunity"]["securitySchemes"] == [{"type": "oauth2", "scopes": ["mcp"]}]
    assert tools["restore_opportunity"]["annotations"]["destructiveHint"] is False
    assert tools["restore_opportunity"]["annotations"]["idempotentHint"] is True
    assert tools["get_collection_queue"]["annotations"]["readOnlyHint"] is True
    assert tools["get_collection_queue"]["securitySchemes"] == [{"type": "oauth2", "scopes": ["mcp"]}]
    assert tools["get_company_maintenance_context"]["annotations"]["readOnlyHint"] is True
    assert tools["get_company_maintenance_context"]["securitySchemes"] == [{"type": "oauth2", "scopes": ["mcp"]}]
    assert tools["list_unmonitored_companies"]["annotations"]["readOnlyHint"] is True
    assert tools["list_companies_missing_profile"]["annotations"]["readOnlyHint"] is True
    assert tools["list_company_profile_history"]["annotations"]["readOnlyHint"] is True
    assert tools["update_collection_target"]["annotations"]["destructiveHint"] is False
    assert tools["patch_opportunity"]["annotations"]["destructiveHint"] is False
    assert tools["preview_opportunity_patch"]["securitySchemes"] == [{"type": "oauth2", "scopes": ["mcp"]}]
    assert tools["find_opportunities_by_source_url"]["securitySchemes"] == [{"type": "noauth"}]
    assert tools["list_stale_opportunities"]["annotations"]["readOnlyHint"] is True
    assert tools["list_stale_opportunities"]["securitySchemes"] == [{"type": "oauth2", "scopes": ["mcp"]}]
    assert tools["resolve_company"]["annotations"]["readOnlyHint"] is True
    assert tools["resolve_company"]["securitySchemes"] == [{"type": "oauth2", "scopes": ["mcp"]}]
    assert tools["add_company_alias"]["annotations"]["destructiveHint"] is False
    assert tools["set_company_industries"]["annotations"]["destructiveHint"] is True
    assert tools["update_company_profile"]["annotations"]["destructiveHint"] is False
    assert tools["update_company_profile"]["annotations"]["idempotentHint"] is True
    assert tools["update_company_profiles"]["annotations"]["idempotentHint"] is True
    assert tools["update_company_profiles"]["annotations"]["readOnlyHint"] is False
    assert tools["set_company_industries"]["annotations"]["idempotentHint"] is True
    assert tools["delete_company_alias"]["annotations"]["destructiveHint"] is True
    assert tools["merge_company"]["annotations"]["destructiveHint"] is True


def test_search_filters_publish_their_allowed_values():
    listed = asyncio.run(mcp_server.mcp.list_tools())
    properties = {tool.name: tool.inputSchema["properties"] for tool in listed}["search_opportunity"]

    assert properties["sort"]["enum"] == ["relevance", "deadline", "updated", "created"]
    assert properties["sort"]["default"] == "relevance"
    assert "募集中" in properties["recruitment_status"]["anyOf"][0]["items"]["enum"]
    assert properties["created_at_after"]["anyOf"][0]["format"] == "date-time"
    assert properties["created_at_after"]["maxLength"] == 64
    assert properties["updated_at_before"]["anyOf"][0]["format"] == "date-time"
    assert set(properties) == {
        "query",
        "recruitment_status",
        "industry",
        "sector",
        "event_type",
        "event_format",
        "job_category",
        "graduation_year",
        "degree",
        "created_at_after",
        "created_at_before",
        "updated_at_after",
        "updated_at_before",
        "sort",
        "cursor",
        "per_page",
    }
    assert all(properties[name].get("description") for name in properties)


def test_write_payload_schema_documents_its_fixed_values_and_rules():
    listed = asyncio.run(mcp_server.mcp.list_tools())
    schemas = {tool.name: tool.inputSchema for tool in listed}
    payload = schemas["add_opportunity"]["properties"]["payload"]

    assert payload["properties"]["industry"]["enum"][0] == "IT・通信"
    assert "get_sectors" in payload["properties"]["sector"]["description"]
    assert payload["properties"]["request_id"]["minLength"] == 8
    assert payload["required"] == sorted(payload["required"], key=payload["required"].index)
    assert all("description" in field for field in payload["properties"].values())


def test_write_description_schema_asks_for_a_concrete_informative_summary():
    listed = asyncio.run(mcp_server.mcp.list_tools())
    tools = {tool.name: tool for tool in listed}
    description = tools["add_opportunity"].inputSchema["properties"]["payload"]["properties"]["description"]

    assert "2〜4文" in description["description"]
    assert "100〜300文字" in description["description"]
    assert "主な業務・プログラム内容" in description["description"]
    assert "推測せず省略" in description["description"]
    assert description["examples"][0].count("。") >= 3

    for name in ("add_opportunity", "upsert_opportunity", "update_opportunity", "patch_opportunity"):
        assert "2〜4文" in tools[name].description


def test_search_returns_summaries_with_a_citable_url(tools, db):
    seed(db)

    result = call("search_opportunity", {"query": "テスト", "industry": ["IT・通信"], "per_page": 5})

    assert result["total"] == 1
    assert result["per_page"] == 5
    hit = result["items"][0]
    assert hit["url"] == f"http://localhost:3100/opportunities/{hit['public_code']}"
    assert hit["company_name"] == "株式会社テスト"
    assert hit["created_at"]
    assert "description" not in hit
    assert hit["description_excerpt"].startswith("プロダクト開発")


def test_search_cursor_does_not_skip_or_repeat_rows_after_deleting_a_previous_page(tools, db):
    deadlines = [date.today() + timedelta(days=days) for days in (1, 2, 3)]
    items = [
        seed(
            db,
            event_name=f"カーソル検証{index}",
            deadline=deadline.isoformat(),
            source_url=f"https://example.com/cursor-{index}",
        )
        for index, deadline in enumerate(deadlines, start=1)
    ]

    first_page = call("search_opportunity", {"sort": "deadline", "per_page": 1})
    assert [item["id"] for item in first_page["items"]] == [items[0].id]
    assert first_page["next_cursor"]

    preview = call("preview_delete_opportunity", {"opportunity_id": items[0].id})
    call(
        "delete_opportunity",
        {
            "opportunity_id": items[0].id,
            "expected_updated_at": preview["expected_updated_at"],
            "request_id": "cursor-delete-0001",
            "client_name": "pytest",
        },
    )
    second_page = call(
        "search_opportunity",
        {"sort": "deadline", "per_page": 1, "cursor": first_page["next_cursor"]},
    )

    assert [item["id"] for item in second_page["items"]] == [items[1].id]
    assert set(item["id"] for item in first_page["items"]).isdisjoint(
        item["id"] for item in second_page["items"]
    )


def test_search_cursor_does_not_repeat_a_returned_row_after_its_deadline_moves(tools, db):
    items = [
        seed(
            db,
            event_name=f"締切移動検証{index}",
            deadline=(date.today() + timedelta(days=index)).isoformat(),
            source_url=f"https://example.com/cursor-move-{index}",
        )
        for index in range(1, 4)
    ]
    first_page = call("search_opportunity", {"sort": "deadline", "per_page": 1})

    call(
        "update_recruitment_status",
        {
            "opportunity_id": items[0].id,
            "expected_updated_at": items[0].updated_at.isoformat(),
            "recruitment_status": "募集中",
            "deadline": (date.today() + timedelta(days=10)).isoformat(),
            "request_id": "cursor-move-0001",
            "client_name": "pytest",
        },
    )
    second_page = call(
        "search_opportunity",
        {"sort": "deadline", "per_page": 1, "cursor": first_page["next_cursor"]},
    )

    assert [item["id"] for item in first_page["items"]] == [items[0].id]
    assert [item["id"] for item in second_page["items"]] == [items[1].id]


def test_search_cursor_rejects_changed_search_conditions(tools, db):
    seed(db, event_name="カーソル条件1", source_url="https://example.com/cursor-filter-1")
    seed(db, event_name="カーソル条件2", source_url="https://example.com/cursor-filter-2")
    first_page = call("search_opportunity", {"sort": "deadline", "per_page": 1})

    error = tool_error(
        "search_opportunity",
        {"sort": "created", "per_page": 1, "cursor": first_page["next_cursor"]},
    )

    assert error["error"] == "invalid_cursor"


def test_search_cursor_rejects_changed_timestamp_filters(tools, db):
    seed(db, event_name="日時条件1", source_url="https://example.com/cursor-time-1")
    seed(db, event_name="日時条件2", source_url="https://example.com/cursor-time-2")
    first_page = call("search_opportunity", {"created_at_after": "2026-01-01T00:00:00Z", "per_page": 1})

    error = tool_error(
        "search_opportunity",
        {
            "created_at_after": "2026-02-01T00:00:00Z",
            "per_page": 1,
            "cursor": first_page["next_cursor"],
        },
    )

    assert error["error"] == "invalid_cursor"


def test_search_filters_by_inclusive_created_and_updated_at_bounds(tools, db):
    postings = [
        seed(db, event_name=f"日時境界{index}", source_url=f"https://example.com/time-bound-{index}")
        for index in range(1, 4)
    ]
    timestamps = [
        (
            datetime(2024, 9, 1, tzinfo=timezone.utc),  # noqa: UP017 -- tests also support Python 3.10
            datetime(2024, 10, 1, tzinfo=timezone.utc),  # noqa: UP017 -- tests also support Python 3.10
        ),
        (
            datetime(2024, 10, 1, tzinfo=timezone.utc),  # noqa: UP017 -- tests also support Python 3.10
            datetime(2024, 10, 2, tzinfo=timezone.utc),  # noqa: UP017 -- tests also support Python 3.10
        ),
        (
            datetime(2024, 10, 2, tzinfo=timezone.utc),  # noqa: UP017 -- tests also support Python 3.10
            datetime(2024, 10, 3, tzinfo=timezone.utc),  # noqa: UP017 -- tests also support Python 3.10
        ),
    ]
    for item, (created_at, updated_at) in zip(postings, timestamps, strict=True):
        item.created_at = created_at
        item.updated_at = updated_at
    db.commit()

    by_creation = call(
        "search_opportunity",
        {
            "created_at_after": "2024-10-01T09:00:00+09:00",
            "created_at_before": "2024-10-02T00:00:00Z",
        },
    )
    by_edit = call(
        "search_opportunity",
        {
            "updated_at_after": "2024-10-02T00:00:00Z",
            "updated_at_before": "2024-10-02T09:00:00+09:00",
        },
    )

    assert {item["id"] for item in by_creation["items"]} == {postings[1].id, postings[2].id}
    assert {item["id"] for item in by_edit["items"]} == {postings[1].id}


def test_search_accepts_the_filters_the_rest_api_has(tools, db):
    seed(db)

    assert call("search_opportunity", {"event_format": ["オンライン"]})["total"] == 1
    assert call("search_opportunity", {"event_format": ["対面"]})["total"] == 0
    assert call("search_opportunity", {"degree": ["学部"]})["total"] == 1
    assert call("search_opportunity", {"degree": ["博士"]})["total"] == 0
    assert call("search_opportunity", {"sector": ["Webサービス"]})["total"] == 1


def test_get_opportunity_resolves_both_references_and_returns_every_field(tools, db):
    item = seed(db)

    by_code = call("get_opportunity", {"reference": item.public_code})
    by_id = call("get_opportunity", {"reference": item.id})

    assert by_code["id"] == by_id["id"] == item.id
    assert by_code["description"] == "プロダクト開発を体験します。"
    assert by_code["url"].endswith(f"/opportunities/{item.public_code}")
    assert by_code["company"]["name"] == "株式会社テスト"
    assert tool_error("get_opportunity", {"reference": "ZZZZZZZZ"})["error"] == "not_found"


def test_get_sectors_narrows_the_choices_to_one_industry(tools, db):
    result = call("get_sectors", {"industry": "IT・通信"})

    names = [sector["name"] for sector in result["sectors"]]
    assert result["industry"]["name"] == "IT・通信"
    assert "Webサービス" in names
    assert "銀行" not in names


def test_find_similar_opportunities_sees_through_company_name_variants(tools, db):
    seed(db)

    matched = call("find_similar_opportunities", {"company_name": "(株)テスト"})
    narrowed = call("find_similar_opportunities", {"company_name": "株式会社テスト", "event_name": "開発インターン"})
    missed = call("find_similar_opportunities", {"company_name": "株式会社無関係"})

    assert [item["event_name"] for item in matched["matches"]] == ["開発インターン"]
    assert len(narrowed["matches"]) == 1
    assert missed["matches"] == []
    assert "新規登録できます" in missed["message"]


COMPANY_SUMMARY = "国内の中堅企業向けに業務システムの受託開発を行い、在庫管理と実績集計の自社SaaSも提供している架空企業です。"
COMPANY_DESCRIPTION = (
    "国内の中堅企業向けに、業務システムの受託開発と自社SaaSの提供を行っています。"
    "受託開発では販売管理と生産管理の領域を中心に、要件定義から設計・開発・運用保守までを一貫して担当します。"
    "顧客は製造業と卸売業が中心で、売上の約7割を受託開発が占めています。\n\n"
    "自社SaaSは在庫管理と実績集計の2製品です。月額課金で提供し、導入企業は約400社です。"
    "受託開発で得た業務知識を製品仕様へ反映する体制をとっており、両事業が同じ開発部門で運営されています。"
    "開発拠点は東京と福岡の2か所で、エンジニアが全社員の6割を占めます。"
    "近年は既存顧客向けにデータ活用の支援業務も始めており、受託開発の周辺領域を広げています。"
)
AREA_RECEIVED_DEVELOPMENT = (
    "販売管理・生産管理システムを個別に開発し、要件定義から設計・開発・運用保守までを担当しています。"
    "製造業と卸売業の中堅企業が主な顧客です。"
)
AREA_SAAS = (
    "在庫管理と実績集計の2製品を月額課金で提供しています。製造業と卸売業を中心に約400社が導入しており、"
    "受託開発で得た業務知識を製品仕様へ反映しています。"
)


def company_profile_payload(**overrides):
    payload = {
        "company_id": None,
        "business_summary": COMPANY_SUMMARY,
        "description": COMPANY_DESCRIPTION,
        "business_areas": [
            {"name": "受託開発事業", "description": AREA_RECEIVED_DEVELOPMENT},
            {"name": "自社SaaS事業", "description": AREA_SAAS},
        ],
        "website_url": "https://profile.example.com/",
        "source_url": "https://profile.example.com/company/",
        "request_id": "mcp-company-profile-0001",
    }
    payload.update(overrides)
    return {"payload": payload}


def test_mcp_writes_a_company_profile_and_replays_the_same_request(tools, db):
    item = seed(db, company_name="株式会社プロフィール")

    written = call("update_company_profile", company_profile_payload(company_id=item.company_id))
    assert written["success"] is True
    assert written["changed"] is True
    assert written["company"]["business_summary"] == COMPANY_SUMMARY
    assert written["company"]["description"] == COMPANY_DESCRIPTION
    assert [area["name"] for area in written["company"]["business_areas"]] == ["受託開発事業", "自社SaaS事業"]
    assert written["company"]["website_url"] == "https://profile.example.com/"
    assert written["company"]["public_code"]
    assert written["company"]["url"].endswith(f"/companies/{written['company']['public_code']}")

    # The profile travels with every company response, not only this tool's own reply.
    resolved = call("resolve_company", {"company_name": "株式会社プロフィール"})["candidates"][0]["company"]
    assert resolved["business_summary"] == COMPANY_SUMMARY
    assert len(resolved["business_areas"]) == 2

    replay = call("update_company_profile", company_profile_payload(company_id=item.company_id))
    assert replay["idempotent_replay"] is True
    assert replay["changed"] is False

    # Omitting a field leaves it alone; business_areas replaces the stored set as a whole.
    patched = call(
        "update_company_profile",
        {
            "payload": {
                "company_id": item.company_id,
                "business_areas": [{"name": "自社SaaS事業", "description": AREA_SAAS}],
                "source_url": "https://profile.example.com/company/",
                "request_id": "mcp-company-profile-0002",
            }
        },
    )
    assert [area["name"] for area in patched["company"]["business_areas"]] == ["自社SaaS事業"]
    assert patched["company"]["business_summary"] == COMPANY_SUMMARY
    assert patched["company"]["website_url"] == "https://profile.example.com/"


def profile_batch_entry(company, **overrides):
    return company_profile_payload(
        company_id=company.id,
        expected_updated_at=company.updated_at.isoformat(),
        request_id=f"profile-batch-{company.id}-0001",
        **overrides,
    )["payload"]


def test_company_profile_batch_publishes_bounds_and_required_snapshot():
    listed = asyncio.run(mcp_server.mcp.list_tools())
    tool = next(tool for tool in listed if tool.name == "update_company_profiles")
    updates = tool.inputSchema["properties"]["updates"]
    assert (updates["minItems"], updates["maxItems"]) == (1, 50)
    assert set(updates["items"]["required"]) == {"company_id", "source_url", "request_id", "expected_updated_at"}
    assert updates["items"]["properties"]["description"]["anyOf"][0]["minLength"] == 300
    assert updates["items"]["properties"]["expected_updated_at"]["format"] == "date-time"
    assert "update_company_profiles" not in mcp_server.ANONYMOUS_TOOLS


def test_company_profile_batch_saves_50_companies_and_replays_without_duplicate_audits(tools, db):
    companies = [Company(name=f"企業{i}", normalized_name=f"企業{i}") for i in range(50)]
    db.add_all(companies)
    db.commit()
    listed = call("list_companies_missing_profile", {"per_page": 50})
    assert len(listed["items"]) == 50
    updates = [
        company_profile_payload(
            company_id=item["id"], expected_updated_at=item["updated_at"], request_id=f"batch-50-{item['id']}-0001"
        )["payload"]
        for item in listed["items"]
    ]
    written = call("update_company_profiles", {"updates": updates})
    assert (written["total"], written["succeeded_count"], written["changed_count"]) == (50, 50, 50)
    assert written["failed_count"] == written["unknown_count"] == written["replayed_count"] == 0
    assert [item["company_id"] for item in written["items"]] == [entry["company_id"] for entry in updates]
    assert all(item["updated_at"] and item["url"] and "description" not in item for item in written["items"])
    assert call("list_companies_missing_profile", {})["total"] == 0
    assert len(list(db.scalars(select(AuditLog)))) == len(list(db.scalars(select(CompanyRequestRecord)))) == 50

    replay = call("update_company_profiles", {"updates": updates})
    assert (replay["succeeded_count"], replay["changed_count"], replay["replayed_count"]) == (50, 0, 50)
    assert len(list(db.scalars(select(AuditLog)))) == 50


def test_company_profile_batch_keeps_successes_around_validation_and_not_found_errors(tools, db):
    companies = [Company(name=f"混在企業{i}", normalized_name=f"混在企業{i}") for i in range(6)]
    db.add_all(companies)
    db.commit()
    updates = [profile_batch_entry(company) for company in companies]
    updates[1]["description"] = "短い"
    updates[2]["source_url"] = "https://www.mynavi.jp/company/"
    updates[3].pop("expected_updated_at")
    updates[4]["company_id"] = 999999

    result = call("update_company_profiles", {"updates": updates})
    assert (result["succeeded_count"], result["failed_count"], result["changed_count"]) == (2, 4, 2)
    assert result["unknown_count"] == 0
    assert [item["success"] for item in result["items"]] == [True, False, False, False, False, True]
    assert result["items"][4]["error"]["error"] == "not_found"
    for index, company in enumerate(companies):
        db.refresh(company)
        assert company.description == (COMPANY_DESCRIPTION if index in (0, 5) else None)
    logs = list(db.scalars(select(AuditLog).where(AuditLog.action == "company_profile_update")))
    assert len(logs) == 6
    assert sum(log.success for log in logs) == 2
    assert {log.request_id: log.source_url for log in logs} == {
        entry["request_id"]: entry["source_url"] for entry in updates
    }
    assert len(list(db.scalars(select(CompanyRequestRecord)))) == 2


def test_company_profile_batch_rejects_stale_snapshots_and_changed_request_reuse(tools, db):
    item = seed(db, company_name="競合企業")
    entry = profile_batch_entry(item.company)
    written = call("update_company_profiles", {"updates": [entry]})
    assert written["changed_count"] == 1
    stored = db.get(Company, item.company_id)
    previous_version = stored.updated_at.replace(tzinfo=UTC)
    stale = entry | {"request_id": "stale-profile-batch-0002", "business_summary": COMPANY_SUMMARY + "更新"}
    conflict = call("update_company_profiles", {"updates": [stale]})
    assert conflict["failed_count"] == 1
    assert "更新されています" in conflict["items"][0]["error"]["errors"][0]["reason"]
    reused = call("update_company_profiles", {"updates": [entry | {"business_summary": COMPANY_SUMMARY + "更新"}]})
    assert reused["failed_count"] == 1
    db.refresh(stored)
    assert stored.business_summary == COMPANY_SUMMARY
    assert stored.updated_at.replace(tzinfo=UTC) == previous_version

    # Equivalent timezone offsets must identify the same retried request.
    equivalent = entry | {
        "expected_updated_at": datetime.fromisoformat(entry["expected_updated_at"])
        .replace(tzinfo=UTC)
        .astimezone(timezone(timedelta(hours=9)))
        .isoformat()
    }
    assert call("update_company_profiles", {"updates": [equivalent]})["replayed_count"] == 1

    unchanged = entry | {"expected_updated_at": written["items"][0]["updated_at"], "request_id": "unchanged-batch-0003"}
    result = call("update_company_profiles", {"updates": [unchanged]})
    assert (result["succeeded_count"], result["changed_count"], result["replayed_count"]) == (1, 0, 0)
    db.refresh(stored)
    assert stored.updated_at.replace(tzinfo=UTC) == previous_version


@pytest.mark.parametrize("size", [0, 51])
def test_company_profile_batch_rejects_invalid_size_before_writing(tools, db, size):
    item = seed(db)
    with pytest.raises(ToolError):
        asyncio.run(mcp_server.mcp.call_tool(
            "update_company_profiles", {"updates": [profile_batch_entry(item.company)] * size}
        ))
    db.refresh(item.company)
    assert item.company.description is None
    assert not list(db.scalars(select(CompanyRequestRecord)))


def test_company_profile_batch_contains_internal_errors_and_continues(tools, db, monkeypatch):
    first = seed(db, company_name="内部エラー企業", event_name="内部エラー募集")
    second = seed(db, company_name="成功企業", event_name="成功募集", source_url="https://example.com/success")
    original = mcp_server.update_company_profile

    def fail_one(session, **kwargs):
        if kwargs["company_id"] == first.company_id:
            session.get(Company, first.company_id).description = "保存してはいけない内容"
            session.flush()
            raise OperationalError("SELECT secret_column", {"private_value": "secret-value"}, Exception("DB failure"))
        return original(session, **kwargs)

    monkeypatch.setattr(mcp_server, "update_company_profile", fail_one)
    result = call(
        "update_company_profiles",
        {"updates": [profile_batch_entry(first.company), profile_batch_entry(second.company)], "run_id": "run-batch-internal"},
    )
    assert (result["succeeded_count"], result["failed_count"], result["unknown_count"]) == (1, 0, 1)
    history = call("list_recent_writes", {"run_id": "run-batch-internal"})
    assert (history["succeeded_count"], history["failed_count"], history["unknown_count"]) == (1, 0, 1)
    assert {item["outcome"] for item in history["items"]} == {"succeeded", "unknown"}
    assert result["items"][0]["success"] is None
    assert result["items"][0]["error"] == mcp_server.INTERNAL_ERROR
    assert "secret_column" not in json.dumps(result)
    assert "secret-value" not in json.dumps(result)
    db.refresh(first.company)
    db.refresh(second.company)
    assert first.company.description is None
    assert second.company.description == COMPANY_DESCRIPTION


def test_company_profile_batch_marks_post_commit_errors_unknown_and_resolves_them_on_retry(tools, db, monkeypatch):
    item = seed(db, company_name="保存結果未確認企業")
    entry = profile_batch_entry(item.company)
    original = mcp_server.update_company_profile

    def lose_response(session, **kwargs):
        original(session, **kwargs)
        raise RuntimeError("Response failed after commit")

    monkeypatch.setattr(mcp_server, "update_company_profile", lose_response)
    result = call("update_company_profiles", {"updates": [entry]})
    assert (result["succeeded_count"], result["failed_count"], result["unknown_count"]) == (0, 0, 1)
    db.refresh(item.company)
    assert item.company.description == COMPANY_DESCRIPTION
    monkeypatch.setattr(mcp_server, "update_company_profile", original)
    replay = call("update_company_profiles", {"updates": [entry]})
    assert (replay["succeeded_count"], replay["replayed_count"], replay["unknown_count"]) == (1, 1, 0)
    logs = list(db.scalars(select(AuditLog).where(AuditLog.action == "company_profile_update", AuditLog.success.is_(True))))
    assert len(logs) == 1


def test_company_profile_batch_isolates_invalid_audit_metadata(tools, db):
    first = seed(db, company_name="入力不備企業", event_name="入力不備募集")
    second = seed(db, company_name="正常企業", event_name="正常募集", source_url="https://example.com/valid")
    invalid = profile_batch_entry(first.company) | {
        "request_id": {"invalid": "object"}, "client_name": ["invalid"], "source_url": {"invalid": "object"}
    }
    result = call("update_company_profiles", {"updates": [invalid, profile_batch_entry(second.company)]})
    assert (result["succeeded_count"], result["failed_count"], result["unknown_count"]) == (1, 1, 0)
    assert result["items"][0]["error"]["error"] == "validation_failed"
    assert result["items"][0]["request_id"] is None
    rejected = db.scalar(select(AuditLog).where(AuditLog.action == "company_profile_update", AuditLog.success.is_(False)))
    assert rejected.source_url is None


def test_company_profile_batch_isolates_oversized_audit_metadata(tools, db):
    first = seed(db, company_name="長さ上限企業", event_name="長さ上限募集")
    second = seed(db, company_name="後続企業", event_name="後続募集", source_url="https://example.com/next")
    invalid = profile_batch_entry(first.company) | {
        "source_url": "https://example.com/" + "a" * 2048,
        "request_id": "r" * 101,
        "client_name": "c" * 101,
    }
    result = call("update_company_profiles", {"updates": [invalid, profile_batch_entry(second.company)]})
    assert (result["succeeded_count"], result["failed_count"], result["unknown_count"]) == (1, 1, 0)
    rejected = db.scalar(select(AuditLog).where(AuditLog.action == "company_profile_update", AuditLog.success.is_(False)))
    assert rejected.source_url is None
    assert rejected.request_id is None
    assert rejected.client_name == "mcp-client"
    db.refresh(first.company)
    db.refresh(second.company)
    assert first.company.description is None
    assert second.company.description == COMPANY_DESCRIPTION


def test_mcp_lists_companies_missing_either_profile_text_field(tools, db):
    missing_both = seed(db, company_name="株式会社説明なし", event_name="説明なし募集")
    summary_only = seed(
        db,
        company_name="株式会社本文なし",
        event_name="本文なし募集",
        source_url="https://example.com/no-body",
    )
    full_profile = seed(
        db,
        company_name="株式会社プロフィール完了",
        event_name="プロフィール完了募集",
        source_url="https://example.com/full-profile",
    )
    whitespace_profile = seed(
        db,
        company_name="株式会社空白プロフィール",
        event_name="空白プロフィール募集",
        source_url="https://example.com/whitespace-profile",
    )
    whitespace_profile.company.business_summary = "\t\n"
    whitespace_profile.company.description = COMPANY_DESCRIPTION
    db.commit()
    call(
        "add_collection_target",
        collection_target_args(
            company_id=missing_both.company_id,
            company_name=None,
            request_id="profile-gap-existing-target-1",
        ),
    )
    call(
        "update_company_profile",
        company_profile_payload(
            company_id=summary_only.company_id,
            description=None,
            business_areas=None,
            website_url=None,
            source_url="https://profile.example.com/company/summary-only",
            request_id="profile-gap-summary-only-1",
        ),
    )
    call(
        "update_company_profile",
        company_profile_payload(
            company_id=full_profile.company_id,
            request_id="profile-gap-full-1",
        ),
    )

    result = call("list_companies_missing_profile", {"per_page": 50})
    missing = {item["id"]: item["missing_profile_fields"] for item in result["items"]}

    assert result["total"] == 3
    assert missing[missing_both.company_id] == ["business_summary", "description"]
    assert missing[summary_only.company_id] == ["description"]
    assert missing[whitespace_profile.company_id] == ["business_summary"]
    assert full_profile.company_id not in missing


def test_mcp_lists_company_profile_history_newest_first(tools, db):
    item = seed(db, company_name="株式会社履歴確認", event_name="履歴確認募集")
    call(
        "update_company_profile",
        company_profile_payload(company_id=item.company_id, request_id="profile-history-mcp-0001"),
    )
    call(
        "update_company_profile",
        company_profile_payload(
            company_id=item.company_id,
            business_summary="プロフィールの要点を更新し、提供サービスと対象顧客を具体的に説明します。",
            request_id="profile-history-mcp-0002",
            source_url="https://profile.example.com/company/updated",
        ),
    )

    history = call("list_company_profile_history", {"company_id": item.company_id})

    assert history["total"] == 2
    assert history["items"][0]["request_id"] == "profile-history-mcp-0002"
    assert history["items"][0]["source_url"] == "https://profile.example.com/company/updated"
    assert history["items"][0]["before"]["business_summary"] == COMPANY_SUMMARY
    assert history["items"][0]["after"]["business_summary"].startswith("プロフィールの要点を更新")
    assert history["items"][1]["request_id"] == "profile-history-mcp-0001"
    assert history["items"][1]["after"]["description"] == COMPANY_DESCRIPTION
    assert tool_error("list_company_profile_history", {"company_id": item.company_id + 1000})["error"] == "not_found"


def test_mcp_company_profile_refuses_a_thin_profile(tools, db):
    item = seed(db, company_name="株式会社ウスイ")

    # A one-line "profile" is the case this tool exists to prevent: the company page would carry a
    # heading and nothing under it.
    thin = tool_error(
        "update_company_profile",
        company_profile_payload(
            company_id=item.company_id,
            business_summary="IT企業です。",
            description="システムを開発しています。",
            business_areas=None,
        ),
    )
    assert thin["error"] == "validation_failed"
    assert {error["field"] for error in thin["errors"]} == {
        FIELD_LABELS["business_summary"],
        FIELD_LABELS["description"],
    }

    short_area = tool_error(
        "update_company_profile",
        company_profile_payload(
            company_id=item.company_id,
            business_areas=[{"name": "受託開発事業", "description": "開発します。"}],
        ),
    )
    assert short_area["error"] == "validation_failed"

    too_many_areas = tool_error(
        "update_company_profile",
        company_profile_payload(
            company_id=item.company_id,
            business_areas=[
                {"name": f"第{index}事業", "description": "製品を開発し、国内の企業向けに提供しています。" * 3}
                for index in range(7)
            ],
        ),
    )
    assert too_many_areas["error"] == "validation_failed"


def test_mcp_company_profile_rejects_aggregator_urls_missing_fields_and_unknown_companies(tools, db):
    item = seed(db, company_name="株式会社リジェクト")

    aggregator = tool_error(
        "update_company_profile",
        company_profile_payload(
            company_id=item.company_id,
            source_url="https://www.rikunabi.com/company/1",
            request_id="mcp-company-profile-reject-1",
        ),
    )
    assert aggregator["error"] == "validation_failed"
    assert aggregator["errors"][0]["field"] == FIELD_LABELS["source_url"]

    empty = tool_error(
        "update_company_profile",
        {
            "payload": {
                "company_id": item.company_id,
                "source_url": "https://reject.example.com/company/",
                "request_id": "mcp-company-profile-reject-2",
            }
        },
    )
    assert empty["error"] == "validation_failed"

    missing = tool_error(
        "update_company_profile",
        company_profile_payload(
            company_id=item.company_id + 9999,
            request_id="mcp-company-profile-reject-3",
        ),
    )
    assert missing["error"] == "not_found"


def test_mcp_can_resolve_register_use_and_remove_a_company_alias(tools, db):
    item = seed(db, company_name="株式会社ディー・エヌ・エー")

    fuzzy = call("resolve_company", {"company_name": "ディーエヌエア"})
    assert fuzzy["match_type"] == "fuzzy"
    assert fuzzy["requires_confirmation"] is True
    assert fuzzy["candidates"][0]["company"]["id"] == item.company_id

    added = call(
        "add_company_alias",
        {
            "company_id": item.company_id,
            "alias": "DeNA",
            "request_id": "mcp-company-alias-add-0001",
        },
    )
    assert added["success"] is True
    assert added["changed"] is True
    alias_id = added["company"]["aliases"][0]["id"]

    exact = call("resolve_company", {"company_name": "dena"})
    assert exact["match_type"] == "alias_exact"
    assert exact["requires_confirmation"] is False
    assert call("search_opportunity", {"query": "DeNA"})["total"] == 1
    assert call("find_similar_opportunities", {"company_name": "ＤｅＮＡ"})["matches"][0]["id"] == item.id

    removed = call(
        "delete_company_alias",
        {"alias_id": alias_id, "request_id": "mcp-company-alias-delete-0001"},
    )
    assert removed["changed"] is True
    assert removed["company"]["aliases"] == []
    missing = call("resolve_company", {"company_name": "DeNA"})
    assert missing["match_type"] == "none"
    assert missing["requires_confirmation"] is True


def test_mcp_company_alias_write_is_idempotent_and_rejects_request_reuse(tools, db):
    item = seed(db, company_name="株式会社ディー・エヌ・エー")
    arguments = {
        "company_id": item.company_id,
        "alias": "DeNA",
        "request_id": "mcp-company-alias-replay-0001",
    }

    assert call("add_company_alias", arguments)["idempotent_replay"] is False
    assert call("add_company_alias", arguments | {"alias": "dena"})["idempotent_replay"] is True
    error = tool_error("add_company_alias", arguments | {"alias": "Mobage"})
    assert error["error"] == "validation_failed"
    assert error["errors"][0]["field"] == "request_id"


def test_mcp_sets_multiple_company_categories_without_a_collection_target(tools, db):
    item = seed(db, company_name="株式会社小売IT")
    arguments = {
        "payload": {
            "company_id": item.company_id,
            "industries": [
                {"industry": "小売・流通", "sector": "EC"},
                {"industry": "IT・通信", "sector": "Webサービス"},
            ],
            "request_id": "mcp-company-industries-0001",
            "client_name": "pytest",
        }
    }

    updated = call("set_company_industries", arguments)
    assert updated["success"] is True
    assert updated["idempotent_replay"] is False
    assert [(row["industry"]["name"], row["sector"]["name"], row["is_primary"]) for row in updated["company"]["industries"]] == [
        ("小売・流通", "EC", True),
        ("IT・通信", "Webサービス", False),
    ]
    audit = db.query(AuditLog).filter_by(action="company_industries_update").one()
    assert audit.changes["before"]["industries"][0]["industry"]["name"] == "IT・通信"
    assert audit.changes["after"]["industries"][0]["industry"]["name"] == "小売・流通"

    replay = call("set_company_industries", arguments)
    assert replay["idempotent_replay"] is True
    assert call("resolve_company", {"company_name": "株式会社小売IT"})["candidates"][0]["company"]["industries"] == updated[
        "company"
    ]["industries"]


def test_mcp_company_category_setting_rejects_duplicate_industries(tools, db):
    item = seed(db, company_name="株式会社カテゴリ重複")
    error = tool_error(
        "set_company_industries",
        {
            "payload": {
                "company_id": item.company_id,
                "industries": [
                    {"industry": "小売・流通", "sector": "EC"},
                    {"industry": "小売・流通", "sector": "専門店"},
                ],
                "request_id": "mcp-company-industries-duplicate-0001",
            }
        },
    )

    assert error["error"] == "validation_failed"
    assert error["errors"][0]["field"] == "業界"
    assert "重複" in error["errors"][0]["reason"]
    assert [row.industry.name for row in item.company.industries] == ["IT・通信"]


def test_mcp_merges_a_confirmed_duplicate_company(tools, db):
    source = seed(
        db,
        company_name="株式会社旧ティス",
        event_name="旧会社のインターン",
        source_url="https://example.com/old-tis-posting",
    )
    target = seed(
        db,
        company_name="TIS株式会社",
        event_name="統合先会社のインターン",
        source_url="https://example.com/tis-posting",
    )
    arguments = {
        "source_company_id": source.company_id,
        "target_company_id": target.company_id,
        "request_id": "mcp-company-merge-0001",
    }

    merged = call("merge_company", arguments)

    assert merged["success"] is True
    assert merged["idempotent_replay"] is False
    assert merged["target_company"]["id"] == target.company_id
    assert merged["migration"]["opportunities_moved"] == 1
    assert {alias["normalized_alias"] for alias in merged["target_company"]["aliases"]} >= {"旧ティス"}
    assert call("merge_company", arguments)["idempotent_replay"] is True


def test_adding_the_same_posting_twice_is_refused_and_points_at_the_existing_entry(tools, db):
    existing = seed(db)

    error = tool_error("add_opportunity", write_args(request_id="duplicate-0001"))

    assert error["error"] == "validation_failed"
    assert error["errors"][0]["existing"][0]["id"] == existing.id
    assert error["errors"][0]["existing"][0]["url"].endswith(f"/opportunities/{existing.public_code}")


def test_a_deliberate_second_entry_still_goes_through(tools, db):
    seed(db)

    result = call("add_opportunity", write_args(request_id="duplicate-0002") | {"allow_duplicate": True})

    assert result["success"] is True
    assert result["opportunity"]["event_name"] == "開発インターン"


def test_upsert_creates_then_returns_the_existing_entry_on_a_repeat(tools, db):
    created = call("upsert_opportunity", write_args(request_id="upsert-0001"))
    assert created["result"] == "created"

    again = call(
        "upsert_opportunity",
        write_args(request_id="upsert-0002", source_url="https://example.com/source-again"),
    )
    assert again["result"] == "existing"
    assert again["opportunity"]["id"] == created["opportunity"]["id"]


def test_upsert_still_raises_on_a_non_duplicate_validation_error(tools, db):
    error = tool_error("upsert_opportunity", write_args(sector="銀行"))
    assert error["errors"][0]["field"] == "業種"


def test_upsert_creates_a_new_row_for_a_different_graduation_year_sharing_the_event_name(tools, db):
    """The exact bug report this guards against: a company reusing "新卒採用エントリー" for both 28卒

    and 29卒 must not make upsert_opportunity silently return the 28卒 posting for a 29卒 registration.
    """
    first = call("upsert_opportunity", write_args(graduation_years=["28卒"], request_id="upsert-grad-0001"))
    assert first["result"] == "created"

    second = call(
        "upsert_opportunity",
        write_args(
            graduation_years=["29卒"],
            source_url="https://example.com/upsert-grad-2",
            request_id="upsert-grad-0002",
        ),
    )
    assert second["result"] == "created"
    assert second["opportunity"]["id"] != first["opportunity"]["id"]
    warning = next(w for w in second["warnings"] if w["field"] == "イベント名")
    assert warning["existing"][0]["id"] == first["opportunity"]["id"]


def test_add_and_upsert_warn_on_a_colliding_source_url_without_blocking_the_write(tools, db):
    seed(db, event_name="既存イベント", source_url="https://example.com/shared-source")

    added = call(
        "add_opportunity",
        write_args(
            request_id="warn-add-0001",
            event_name="新しいイベント",
            source_url="https://example.com/shared-source",
        ),
    )
    assert added["success"] is True
    assert added["warnings"][0]["existing"][0]["event_name"] == "既存イベント"

    upserted = call(
        "upsert_opportunity",
        write_args(
            request_id="warn-upsert-0001",
            event_name="別の新しいイベント",
            source_url="https://example.com/shared-source",
        ),
    )
    assert upserted["result"] == "created"
    warned_event_names = {item["event_name"] for item in upserted["warnings"][0]["existing"]}
    assert "既存イベント" in warned_event_names


def test_add_reports_a_bad_field_in_the_structured_error_shape(tools, db):
    error = tool_error("add_opportunity", write_args(deadline="2026/08/31"))

    assert error["error"] == "validation_failed"
    assert error["errors"][0]["field"] == "締め切り"
    assert error["errors"][0]["expected"].startswith("YYYY-MM-DD")
    assert error["errors"][0]["example"] == "2026-08-31"


def test_add_reports_a_bad_fixed_value_with_the_available_choices(tools, db):
    error = tool_error("add_opportunity", write_args(sector="銀行"))

    assert error["errors"][0]["field"] == "業種"
    assert "Webサービス" in error["errors"][0]["expected"]


def test_validate_checks_the_payload_without_writing_anything(tools, db):
    ok = call("validate_opportunity", write_args(request_id="validate-0001"))
    assert ok["valid"] is True
    assert ok["duplicates"] == []
    assert call("search_opportunity", {})["total"] == 0

    seed(db)
    warned = call("validate_opportunity", write_args(request_id="validate-0002"))
    assert warned["valid"] is True
    assert len(warned["duplicates"]) == 1

    error = tool_error("validate_opportunity", write_args(request_id="validate-0003", sector="銀行"))
    assert error["errors"][0]["field"] == "業種"
    assert call("search_opportunity", {})["total"] == 1


def test_validate_opportunity_treats_a_different_graduation_year_as_probable_not_exact(tools, db):
    seed(db, graduation_years=["28卒"])

    validated = call(
        "validate_opportunity",
        write_args(
            graduation_years=["29卒"],
            source_url="https://example.com/validate-grad-2",
            request_id="validate-grad-0001",
        ),
    )

    assert validated["valid"] is True
    assert validated["duplicates"] == []
    warning = next(w for w in validated["warnings"] if w["field"] == "イベント名")
    assert warning["existing"][0]["event_name"] == "開発インターン"


def test_source_url_matching_ignores_tracking_parameters_and_warns_on_validation(tools, db):
    existing = seed(db)
    variant = "https://EXAMPLE.com/source/?utm_source=chatgpt#details"

    matches = call("find_opportunities_by_source_url", {"source_url": variant})["matches"]
    validated = call(
        "validate_opportunity",
        write_args(
            request_id="source-duplicate-0001",
            company_name="株式会社別企業",
            event_name="別イベント",
            source_url=variant,
        ),
    )

    assert [item["id"] for item in matches] == [existing.id]
    assert [item["id"] for item in validated["duplicates"]] == [existing.id]


def test_patch_preview_updates_only_selected_fields_and_rejects_stale_writes(tools, db):
    item = seed(db)
    current = call("get_opportunity", {"reference": item.id})
    new_deadline = (date.today() + timedelta(days=75)).isoformat()
    arguments = {
        "opportunity_id": item.id,
        "changes": {"deadline": new_deadline},
        "expected_updated_at": current["updated_at"],
        "request_id": "patch-opportunity-0001",
        "client_name": "pytest",
    }

    preview = call("preview_opportunity_patch", arguments | {"request_id": "patch-preview-0001"})
    updated = call("patch_opportunity", arguments)
    replay = call("patch_opportunity", arguments)

    assert preview["changes"] == [
        {"field": "deadline", "before": current["deadline"], "after": new_deadline}
    ]
    assert updated["opportunity"]["deadline"] == new_deadline
    assert updated["opportunity"]["description"] == current["description"]
    assert replay["idempotent_replay"] is True

    stale = tool_error(
        "patch_opportunity",
        arguments
        | {
            "changes": {"deadline": (date.today() + timedelta(days=90)).isoformat()},
            "request_id": "patch-opportunity-0002",
        },
    )
    assert stale["errors"][0]["field"] == "更新前の最終確認日時"


def test_patch_opportunity_writes_content_without_claiming_a_fresh_source_check(tools, db):
    """write != verify: patch_opportunity only changes DB content. A caller who actually re-read the

    primary source records that separately via verify_opportunity or record_collection_check.
    """
    item = seed(db)
    original_checked_at = item.source_checked_at
    current = call("get_opportunity", {"reference": item.id})

    updated = call(
        "patch_opportunity",
        {
            "opportunity_id": item.id,
            "changes": {"description": "タグ・分類だけを修正しました。"},
            "expected_updated_at": current["updated_at"],
            "request_id": "patch-no-verify-0001",
            "client_name": "pytest",
        },
    )

    assert updated["opportunity"]["description"] == "タグ・分類だけを修正しました。"
    assert updated["opportunity"]["updated_at"] != current["updated_at"]
    assert (
        datetime.fromisoformat(updated["opportunity"]["source_checked_at"].replace("Z", "+00:00"))
        == original_checked_at
    )


def test_patch_and_update_opportunity_no_longer_accept_collection_target_id(tools):
    """That parameter only ever made sense for a brand-new registration; see

    test_patch_opportunity_writes_content_without_claiming_a_fresh_source_check for the write/verify
    split this schema change enforces.
    """
    listed = asyncio.run(mcp_server.mcp.list_tools())
    schemas = {tool.name: tool.inputSchema for tool in listed}
    assert "collection_target_id" not in schemas["patch_opportunity"]["properties"]
    assert "collection_target_id" not in schemas["update_opportunity"]["properties"]
    assert "collection_target_id" in schemas["add_opportunity"]["properties"]
    assert "collection_target_id" in schemas["upsert_opportunity"]["properties"]


def test_update_opportunity_requires_expected_updated_at_and_rejects_stale_writes(tools, db):
    """update_opportunity is a full replacement, so it needs the same optimistic lock as

    patch_opportunity/delete_opportunity - otherwise a caller working from a stale get_opportunity
    read can silently overwrite a concurrent edit (lost update).
    """
    item = seed(db)
    current = call("get_opportunity", {"reference": item.id})
    schema = asyncio.run(mcp_server.mcp.list_tools())
    required = next(tool for tool in schema if tool.name == "update_opportunity").inputSchema["required"]
    assert "expected_updated_at" in required

    new_deadline = (date.today() + timedelta(days=80)).isoformat()
    updated = call(
        "update_opportunity",
        {
            "opportunity_id": item.id,
            "payload": valid_payload() | {"deadline": new_deadline, "request_id": "update-lock-0001", "client_name": "pytest"},
            "expected_updated_at": current["updated_at"],
        },
    )
    assert updated["opportunity"]["deadline"] == new_deadline

    stale = tool_error(
        "update_opportunity",
        {
            "opportunity_id": item.id,
            "payload": valid_payload()
            | {"deadline": (date.today() + timedelta(days=95)).isoformat(), "request_id": "update-lock-0002", "client_name": "pytest"},
            "expected_updated_at": current["updated_at"],
        },
    )
    assert stale["errors"][0]["field"] == "更新前の最終確認日時"


def test_update_recruitment_status_touches_only_the_status_and_deadline(tools, db):
    item = seed(db)
    new_deadline = (date.today() + timedelta(days=60)).isoformat()
    original_checked_at = item.source_checked_at

    schema = asyncio.run(mcp_server.mcp.list_tools())
    required = next(tool for tool in schema if tool.name == "update_recruitment_status").inputSchema["required"]
    assert "expected_updated_at" in required

    result = call(
        "update_recruitment_status",
        {
            "opportunity_id": item.id,
            "expected_updated_at": item.updated_at.isoformat(),
            "recruitment_status": "締切",
            "deadline": new_deadline,
            "request_id": "status-update-0001",
            "client_name": "pytest",
        },
    )

    assert result["opportunity"]["recruitment_status"]["name"] == "締切"
    assert result["opportunity"]["deadline"] == new_deadline
    assert result["opportunity"]["description"] == "プロダクト開発を体験します。"
    assert result["opportunity"]["event_name"] == "開発インターン"
    assert datetime.fromisoformat(result["opportunity"]["source_checked_at"].replace("Z", "+00:00")) == original_checked_at
    assert result["warnings"][0]["reason"] == "締め切りが未来ですが募集状況は「締切」です"


def test_update_recruitment_status_rejects_a_stale_version(tools, db):
    item = seed(db)
    stale_version = item.updated_at.isoformat()
    call(
        "patch_opportunity",
        {
            "opportunity_id": item.id,
            "changes": {"description": "先に保存された変更です。"},
            "expected_updated_at": stale_version,
            "request_id": "status-lock-patch-0001",
            "client_name": "pytest",
        },
    )

    error = tool_error(
        "update_recruitment_status",
        {
            "opportunity_id": item.id,
            "expected_updated_at": stale_version,
            "recruitment_status": "締切",
            "request_id": "status-lock-stale-0001",
            "client_name": "pytest",
        },
    )

    assert error["errors"][0]["field"] == "更新前の最終確認日時"


def test_updates_return_soft_warnings_for_date_and_status_contradictions(tools, db):
    item = seed(db)
    today = today_in_tokyo()
    closed = call(
        "update_recruitment_status",
        {
            "opportunity_id": item.id,
            "expected_updated_at": item.updated_at.isoformat(),
            "recruitment_status": "締切",
            "deadline": (today + timedelta(days=30)).isoformat(),
            "request_id": "soft-warning-closed-0001",
            "client_name": "pytest",
        },
    )
    preview = call(
        "preview_opportunity_patch",
        {
            "opportunity_id": item.id,
            "changes": {"event_start_date": (today + timedelta(days=60)).isoformat()},
            "expected_updated_at": closed["opportunity"]["updated_at"],
            "request_id": "soft-warning-preview-0001",
            "client_name": "pytest",
        },
    )
    reopened = call(
        "update_recruitment_status",
        {
            "opportunity_id": item.id,
            "expected_updated_at": closed["opportunity"]["updated_at"],
            "recruitment_status": "募集中",
            "deadline": (today - timedelta(days=1)).isoformat(),
            "request_id": "soft-warning-open-0001",
            "client_name": "pytest",
        },
    )

    assert {warning["reason"] for warning in preview["warnings"]} >= {
        "締め切りが未来ですが募集状況は「締切」です",
        "実施開始日が未来ですが募集状況は「締切」です",
    }
    assert reopened["success"] is True
    assert any(warning["reason"] == "締め切りが過去ですが募集状況は「募集中」です" for warning in reopened["warnings"])


def test_validate_opportunity_returns_soft_date_status_warnings(tools, db):
    today = today_in_tokyo()

    validated = call(
        "validate_opportunity",
        write_args(
            recruitment_status="締切",
            deadline=(today + timedelta(days=30)).isoformat(),
            event_start_date=(today + timedelta(days=60)).isoformat(),
            request_id="soft-warning-validate-0001",
        ),
    )

    assert validated["valid"] is True
    assert {warning["reason"] for warning in validated["warnings"]} == {
        "締め切りが未来ですが募集状況は「締切」です",
        "実施開始日が未来ですが募集状況は「締切」です",
    }


def test_update_recruitment_status_replays_instead_of_writing_twice(tools, db):
    item = seed(db)
    arguments = {
        "opportunity_id": item.id,
        "expected_updated_at": item.updated_at.isoformat(),
        "recruitment_status": "締切",
        "request_id": "status-replay-0001",
        "client_name": "pytest",
    }

    first = call("update_recruitment_status", arguments)
    second = call("update_recruitment_status", arguments)

    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True


def test_update_recruitment_status_rejects_an_unusable_date(tools, db):
    item = seed(db)

    error = tool_error(
        "update_recruitment_status",
        {
            "opportunity_id": item.id,
            "expected_updated_at": item.updated_at.isoformat(),
            "recruitment_status": "締切",
            "deadline": "2026/09/01",
            "request_id": "status-bad-date-0001",
        },
    )

    assert error["errors"][0]["field"] == "締め切り"
    assert tool_error(
        "update_recruitment_status",
        {
            "opportunity_id": "missing",
            "expected_updated_at": item.updated_at.isoformat(),
            "recruitment_status": "締切",
            "request_id": "status-missing-0001",
        },
    )["error"] == "not_found"


def test_verify_opportunity_records_an_unchanged_source_without_touching_updated_at(tools, db):
    item = seed(db)
    original_updated_at = item.updated_at
    original_checked_at = item.source_checked_at
    checked_at = datetime.now(timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
    arguments = {
        "opportunity_id": item.id,
        "checked_at": checked_at.isoformat(),
        "source_url": item.source_url,
        "request_id": "verify-opportunity-0001",
        "client_name": "pytest",
    }

    verified = call("verify_opportunity", arguments)
    replay = call("verify_opportunity", arguments)

    assert verified["idempotent_replay"] is False
    assert replay["idempotent_replay"] is True
    assert datetime.fromisoformat(verified["opportunity"]["updated_at"].replace("Z", "+00:00")) == original_updated_at
    assert datetime.fromisoformat(verified["opportunity"]["source_checked_at"].replace("Z", "+00:00")) == checked_at
    assert item.source_checked_at == checked_at
    assert item.source_checked_at > original_checked_at
    audit = db.query(AuditLog).filter_by(request_id="verify-opportunity-0001").one()
    assert audit.action == "verify"
    assert audit.source_url == item.source_url
    assert audit.changes["before"]["source_checked_at"] == original_checked_at.isoformat()
    assert audit.changes["after"] == {
        "source_checked_at": checked_at.isoformat(), "date_status_reviewed_at": None,
    }


def test_verify_opportunity_rejects_a_different_or_future_source_check(tools, db):
    item = seed(db)
    common = {
        "opportunity_id": item.id,
        "checked_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 -- tests also support Python 3.10
        "request_id": "verify-source-mismatch-0001",
    }

    source_error = tool_error(
        "verify_opportunity", common | {"source_url": "https://example.com/other-official-page"}
    )
    future_error = tool_error(
        "verify_opportunity",
        {
            "opportunity_id": item.id,
            "checked_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),  # noqa: UP017 -- tests also support Python 3.10
            "source_url": item.source_url,
            "request_id": "verify-future-0001",
        },
    )

    assert source_error["errors"][0]["field"] == "情報源"
    assert future_error["errors"][0]["field"] == "確認日時"


def test_delete_preview_soft_delete_and_restore_preserve_the_record(tools, db):
    item = seed(db)
    preview = call("preview_delete_opportunity", {"opportunity_id": item.id})
    current = call("get_opportunity", {"reference": item.id})
    arguments = {
        "opportunity_id": item.id,
        "expected_updated_at": preview["expected_updated_at"],
        "request_id": "delete-opportunity-0001",
        "client_name": "pytest",
    }

    deleted = call("delete_opportunity", arguments)
    replay = call("delete_opportunity", arguments)
    restored = call(
        "restore_opportunity",
        {
            "opportunity_id": item.id,
            "request_id": "restore-opportunity-0001",
            "client_name": "pytest",
        },
    )
    restore_replay = call(
        "restore_opportunity",
        {
            "opportunity_id": item.id,
            "request_id": "restore-opportunity-0001",
            "client_name": "pytest",
        },
    )

    assert preview["opportunity"]["id"] == item.id
    assert preview["linked_collection_checks"] == 0
    assert preview["expected_updated_at"] == current["updated_at"]
    assert len(preview["effects"]) == 3
    assert deleted["success"] is True
    assert deleted["idempotent_replay"] is False
    assert deleted["deleted"]["id"] == item.id
    assert deleted["deleted"]["public_code"] == item.public_code
    assert deleted["deleted"]["company_name"] == "株式会社テスト"
    assert deleted["deleted"]["event_name"] == "開発インターン"
    assert deleted["deleted"]["source_url"] == "https://example.com/source"
    assert deleted["deleted"]["deleted_at"] is not None
    assert replay["idempotent_replay"] is True
    assert replay["deleted"] == deleted["deleted"]
    stored = db.get(Opportunity, item.id)
    assert stored is not None
    assert stored.deleted_at is None
    assert restored["opportunity"]["id"] == item.id
    assert restored["opportunity"]["public_code"] == item.public_code
    assert restore_replay["idempotent_replay"] is True
    assert call("search_opportunity", {})["total"] == 1
    assert call("get_opportunity", {"reference": item.id})["id"] == item.id

    history = call("list_recent_writes", {"limit": 10})["items"]
    assert [entry["action"] for entry in history] == ["restore", "delete", "create"]


def test_delete_opportunity_rejects_stale_data_and_reused_request_ids(tools, db):
    item = seed(db)
    current = call("get_opportunity", {"reference": item.id})
    call(
        "patch_opportunity",
        {
            "opportunity_id": item.id,
            "changes": {"description": "更新後の説明です。"},
            "expected_updated_at": current["updated_at"],
            "request_id": "patch-before-delete-0001",
            "client_name": "pytest",
        },
    )

    stale = tool_error(
        "delete_opportunity",
        {
            "opportunity_id": item.id,
            "expected_updated_at": current["updated_at"],
            "request_id": "delete-stale-0001",
            "client_name": "pytest",
        },
    )
    reused = tool_error(
        "delete_opportunity",
        {
            "opportunity_id": item.id,
            "expected_updated_at": call("get_opportunity", {"reference": item.id})["updated_at"],
            "request_id": "patch-before-delete-0001",
            "client_name": "pytest",
        },
    )

    assert stale["errors"][0]["field"] == "更新前の最終確認日時"
    assert reused["errors"][0]["field"] == "request_id"
    assert call("get_opportunity", {"reference": item.id})["description"] == "更新後の説明です。"


def test_soft_deleted_opportunity_is_hidden_until_restored(tools, db):
    item = seed(db)
    preview = call("preview_delete_opportunity", {"opportunity_id": item.id})

    call(
        "delete_opportunity",
        {
            "opportunity_id": item.id,
            "expected_updated_at": preview["expected_updated_at"],
            "request_id": "delete-hidden-0001",
            "client_name": "pytest",
        },
    )

    assert call("search_opportunity", {})["total"] == 0
    assert tool_error("get_opportunity", {"reference": item.id})["error"] == "not_found"
    assert tool_error("preview_delete_opportunity", {"opportunity_id": item.id})["error"] == "not_found"
    assert db.get(Opportunity, item.id) is not None
    assert db.get(Opportunity, item.id).deleted_at is not None


def test_restore_rejects_a_new_active_duplicate(tools, db):
    item = seed(db)
    preview = call("preview_delete_opportunity", {"opportunity_id": item.id})
    call(
        "delete_opportunity",
        {
            "opportunity_id": item.id,
            "expected_updated_at": preview["expected_updated_at"],
            "request_id": "delete-before-replace-0001",
            "client_name": "pytest",
        },
    )
    replacement = call(
        "add_opportunity",
        write_args(request_id="replacement-opportunity-0001"),
    )

    error = tool_error(
        "restore_opportunity",
        {
            "opportunity_id": item.id,
            "request_id": "restore-duplicate-0001",
            "client_name": "pytest",
        },
    )

    assert "対象学年・実施日・対象職種も一致" in error["errors"][0]["reason"]
    assert error["errors"][0]["existing"][0]["id"] == replacement["opportunity"]["id"]
    assert call("search_opportunity", {})["total"] == 1


def test_restore_allows_a_same_named_posting_with_a_different_cohort(tools, db):
    original = seed(db, graduation_years=["28卒"])
    preview = call("preview_delete_opportunity", {"opportunity_id": original.id})
    call(
        "delete_opportunity",
        {
            "opportunity_id": original.id,
            "expected_updated_at": preview["expected_updated_at"],
            "request_id": "delete-before-cohort-restore-0001",
            "client_name": "pytest",
        },
    )
    call(
        "add_opportunity",
        write_args(
            graduation_years=["29卒"],
            source_url="https://example.com/source-29",
            request_id="replacement-cohort-0001",
        ),
    )

    restored = call(
        "restore_opportunity",
        {
            "opportunity_id": original.id,
            "request_id": "restore-different-cohort-0001",
            "client_name": "pytest",
        },
    )

    assert restored["success"] is True
    assert call("search_opportunity", {})["total"] == 2


def test_list_recent_writes_reports_successes_and_failures(tools, db):
    seed(db)
    tool_error("add_opportunity", write_args(request_id="history-fail-0001", event_name="別の募集", sector="銀行"))

    history = call("list_recent_writes", {"limit": 10})["items"]

    assert [entry["success"] for entry in history] == [False, True]
    assert history[0]["errors"][0]["field"] == "業種"
    assert history[1]["url"].endswith("/opportunities/" + call("search_opportunity", {})["items"][0]["public_code"])
    assert call("list_recent_writes", {"client_name": "nobody"})["items"] == []


def test_list_recent_writes_reports_company_profile_updates_and_their_rejections(tools, db):
    """A rejected company profile write was invisible here, so an agent reported that none had failed."""
    item = seed(db, company_name="株式会社プロフィール")
    call("update_company_profile", company_profile_payload(company_id=item.company_id))
    tool_error(
        "update_company_profile",
        company_profile_payload(company_id=item.company_id, business_summary="短い", request_id="mcp-company-profile-0002"),
    )

    history = call("list_recent_writes", {"limit": 10})["items"]
    assert [(entry["entity_type"], entry["success"]) for entry in history] == [
        ("company", False),
        ("company", True),
        ("opportunity", True),
    ]
    rejected = history[0]
    assert rejected["action"] == "company_profile_update"
    assert rejected["errors"][0]["field"] == FIELD_LABELS["business_summary"]
    assert rejected["opportunity_id"] is None
    assert rejected["url"] is None
    assert history[1]["entity_id"] == str(item.company_id)
    assert history[1]["url"] is None
    assert history[2]["opportunity_id"] == history[2]["entity_id"] == item.id

    companies = call("list_recent_writes", {"entity_type": "company"})["items"]
    assert [entry["request_id"] for entry in companies] == ["mcp-company-profile-0002", "mcp-company-profile-0001"]
    assert [entry["entity_type"] for entry in call("list_recent_writes", {"entity_type": "opportunity"})["items"]] == [
        "opportunity"
    ]


def test_list_recent_writes_reports_collection_writes(tools):
    target = call("add_collection_target", collection_target_args(request_id="history-collection-0001"))["target"]

    history = call("list_recent_writes", {"limit": 10})["items"]
    assert "collection_target" in {entry["entity_type"] for entry in history}

    targets = call("list_recent_writes", {"entity_type": "collection_target"})["items"]
    assert [(entry["request_id"], entry["entity_id"]) for entry in targets] == [
        ("history-collection-0001", str(target["id"]))
    ]
    assert targets[0]["opportunity_id"] is None


def test_list_stale_opportunities_flags_records_not_recently_confirmed(tools, db):
    fresh = seed(db, company_name="株式会社新着", source_url="https://example.com/stale-tool-fresh")
    stale = seed(
        db,
        company_name="株式会社古参",
        event_name="長期インターン",
        source_url="https://example.com/stale-tool-old",
    )
    stale.source_checked_at = datetime.now(timezone.utc) - timedelta(days=40)  # noqa: UP017 -- tests also support Python 3.10
    db.commit()

    result = call("list_stale_opportunities", {"days": 7})

    ids = [item["id"] for item in result["items"]]
    assert stale.id in ids
    assert fresh.id not in ids
    assert result["items"][0]["id"] == stale.id
    assert result["items"][0]["review_reasons"] == ["source_not_checked_recently"]


def test_review_queue_prioritizes_open_postings_with_past_dates(tools, db):
    stale = seed(
        db,
        company_name="株式会社通常再確認",
        source_url="https://example.com/review-queue-stale",
    )
    stale.source_checked_at = datetime.now(timezone.utc) - timedelta(days=40)  # noqa: UP017 -- tests also support Python 3.10
    today = date.today()
    conflict = seed(
        db,
        company_name="株式会社矛盾確認",
        event_name="期限矛盾インターン",
        deadline=(today - timedelta(days=1)).isoformat(),
        event_end_date=(today - timedelta(days=2)).isoformat(),
        source_url="https://example.com/review-queue-conflict",
    )
    db.commit()

    result = call("list_stale_opportunities", {"days": 7})
    items = {item["id"]: item for item in result["items"]}

    assert result["items"][0]["id"] == conflict.id
    assert items[conflict.id]["review_reasons"] == [
        "deadline_passed_while_open",
        "event_ended_while_open",
    ]
    assert items[stale.id]["review_reasons"] == ["source_not_checked_recently"]
    call("verify_opportunity", {
        "opportunity_id": conflict.id, "checked_at": datetime.now(UTC).isoformat(),
        "source_url": conflict.source_url, "request_id": "review-queue-confirmed-0001", "client_name": "pytest",
    })
    assert [item["id"] for item in call("list_stale_opportunities", {"limit": 1})["items"]] == [stale.id]


def collection_target_args(**overrides) -> dict:
    industry = overrides.pop("industry", "IT・通信")
    sector = overrides.pop("sector", "Webサービス")
    payload = {
        "company_name": "株式会社収集テスト",
        "industries": [{"industry": industry, "sector": sector}],
        "priority_tier": 1,
        "check_interval_days": 14,
        "selection_reason": "業界内の掲載範囲を確認するため",
        "sources": [{"source_type": "recruit", "url": "https://example.com/recruit"}],
        "request_id": "collection-create-0001",
        "client_name": "pytest",
    }
    return {"payload": payload | overrides}


def test_list_collection_targets_filters_by_current_check_status(tools):
    unreviewed = call(
        "add_collection_target",
        collection_target_args(company_name="株式会社未確認", request_id="status-filter-target-1"),
    )["target"]
    no_opening = call(
        "add_collection_target",
        collection_target_args(company_name="株式会社募集なし", request_id="status-filter-target-2"),
    )["target"]
    call(
        "record_collection_check",
        {
            "target_id": no_opening["id"],
            "payload": {
                "result": "no_opening",
                "source_url": "https://example.com/recruit",
                "request_id": "status-filter-check-0001",
                "client_name": "pytest",
            },
        },
    )

    unreviewed_result = call("list_collection_targets", {"check_statuses": ["unreviewed"]})
    no_opening_result = call("list_collection_targets", {"check_statuses": ["no_active_opportunity"]})
    combined = call("list_collection_targets", {"check_statuses": ["unreviewed", "no_active_opportunity"]})

    assert [item["id"] for item in unreviewed_result["items"]] == [unreviewed["id"]]
    assert [item["id"] for item in no_opening_result["items"]] == [no_opening["id"]]
    assert {item["id"] for item in combined["items"]} == {unreviewed["id"], no_opening["id"]}
    assert combined["total"] == 2


def test_collection_targets_allow_large_operator_imports(tools):
    for index in range(100):
        created = call(
            "add_collection_target",
            collection_target_args(
                company_name=f"株式会社一括登録{index:03d}",
                sources=[{"source_type": "recruit", "url": f"https://example.com/recruit/{index}"}],
                request_id=f"bulk-collection-{index:03d}",
            ),
        )
        assert created["success"] is True

    assert call("list_collection_targets", {"limit": 100})["total"] == 100


def test_opportunity_write_can_complete_collection_target_atomically(tools, db):
    target = call(
        "add_collection_target",
        collection_target_args(
            company_name="株式会社テスト",
            sources=[{"source_type": "recruit", "url": "https://example.com/source"}],
            request_id="collection-for-write-0001",
        ),
    )["target"]

    written = call(
        "add_opportunity",
        write_args(request_id="opportunity-with-target-0001")
        | {"collection_target_id": target["id"]},
    )
    refreshed = call("get_collection_target", {"target_id": target["id"]})
    checks = call("list_collection_checks", {"target_id": target["id"]})["items"]

    assert written["success"] is True
    assert refreshed["last_check_result"] == "found"
    assert refreshed["last_found_at"] is not None
    assert checks[0]["opportunity_id"] == written["opportunity"]["id"]
    assert checks[0]["request_id"] == "opportunity-with-target-0001"

    preview = call(
        "preview_delete_opportunity",
        {"opportunity_id": written["opportunity"]["id"]},
    )
    assert preview["linked_collection_checks"] == 1
    call(
        "delete_opportunity",
        {
            "opportunity_id": written["opportunity"]["id"],
            "expected_updated_at": preview["expected_updated_at"],
            "request_id": "delete-with-target-0001",
            "client_name": "pytest",
        },
    )
    assert call("get_collection_target", {"target_id": target["id"]})["opportunities"] == []
    assert call("list_collection_checks", {"target_id": target["id"]})["items"][0]["opportunity_id"] == written["opportunity"]["id"]

    call(
        "restore_opportunity",
        {
            "opportunity_id": written["opportunity"]["id"],
            "request_id": "restore-with-target-0001",
            "client_name": "pytest",
        },
    )
    restored_target = call("get_collection_target", {"target_id": target["id"]})
    assert restored_target["opportunities"][0]["id"] == written["opportunity"]["id"]


def test_list_undercovered_companies_orders_by_fewest_linked_opportunities(tools, db):
    uncovered = call("add_collection_target", collection_target_args())["target"]
    covered = call(
        "add_collection_target",
        collection_target_args(company_name="株式会社充足済み", request_id="collection-create-0002"),
    )["target"]
    call(
        "add_opportunity",
        write_args(
            company_name="株式会社充足済み",
            source_url="https://example.com/undercovered-mcp-posting",
            request_id="undercovered-mcp-write-0001",
        ),
    )

    assert [item["id"] for item in call("list_undercovered_companies", {"industry": "IT・通信"})["items"]] == [uncovered["id"]]
    db.get(CollectionTarget, covered["id"]).next_check_at = datetime.now(UTC) - timedelta(days=1)
    db.commit()
    items = call("list_undercovered_companies", {"industry": "IT・通信"})["items"]
    ids = [item["id"] for item in items]
    assert ids.index(uncovered["id"]) < ids.index(covered["id"])
    assert next(item for item in items if item["id"] == uncovered["id"])["company_opportunity_count"] == 0
    assert next(item for item in items if item["id"] == covered["id"])["company_opportunity_count"] == 1


def test_collection_target_schema_is_actionable_for_mcp_clients():
    listed = asyncio.run(mcp_server.mcp.list_tools())
    schemas = {tool.name: tool.inputSchema for tool in listed}
    payload = schemas["add_collection_target"]["properties"]["payload"]

    industries = payload["properties"]["industries"]
    assert industries["items"]["properties"]["industry"]["enum"][0] == "IT・通信"
    assert industries["minItems"] == 1
    assert "複数指定" in industries["description"]
    assert payload["properties"]["priority_tier"]["minimum"] == 1
    assert any(item.get("minimum") == 1 for item in payload["properties"]["company_id"]["anyOf"])
    assert "company_name" in payload["properties"]
    assert payload["properties"]["sources"]["items"]["properties"]["url"]["description"]
    target_filters = schemas["list_collection_targets"]["properties"]
    assert target_filters["check_statuses"]["anyOf"][0]["items"]["enum"] == [
        "unreviewed",
        "found",
        "no_active_opportunity",
        "source_unavailable",
        "needs_review",
    ]
    assert schemas["record_collection_check"]["properties"]["payload"]["properties"]["result"]["enum"] == [
        "found",
        "no_opening",
        "unreachable",
        "needs_review",
    ]
    check_payload = schemas["record_collection_check"]["properties"]["payload"]
    assert {"result", "source_url", "request_id"}.issubset(check_payload["required"])
    assert "実際に確認" in check_payload["properties"]["source_url"]["description"]


def test_history_tools_report_database_retention_days(tools):
    target = call("add_collection_target", collection_target_args())["target"]
    assert call("list_recent_writes", {})["retention_days"] == 90
    assert call("list_collection_checks", {"target_id": target["id"]})["retention_days"] == 90
    assert call("list_company_profile_history", {"company_id": target["company"]["id"]})["retention_days"] == 90


def test_company_industry_schema_documents_multiple_categories():
    listed = asyncio.run(mcp_server.mcp.list_tools())
    payload = {tool.name: tool.inputSchema for tool in listed}["set_company_industries"]["properties"]["payload"]

    industries = payload["properties"]["industries"]
    assert industries["minItems"] == 1
    assert industries["maxItems"] == 14
    assert "複数指定" in industries["description"]
    assert payload["properties"]["company_id"]["minimum"] == 1


def test_mcp_lists_unmonitored_companies_and_adds_one_by_id(tools, db):
    salesforce = seed(
        db,
        company_name="Salesforce",
        source_url="https://example.com/salesforce-unmonitored-posting",
    )
    adobe = seed(
        db,
        company_name="Adobe",
        event_name="Adobe未監視インターン",
        source_url="https://example.com/adobe-unmonitored-posting",
    )
    target_args = collection_target_args(
        company_id=salesforce.company_id,
        request_id="mcp-existing-company-target-0001",
        sources=[{"source_type": "recruit", "url": "https://example.com/salesforce-unmonitored-careers"}],
    )
    del target_args["payload"]["company_name"]

    created = call("add_collection_target", target_args)
    missing = call("list_unmonitored_companies", {"query": "Adobe"})

    assert created["target"]["company"]["id"] == salesforce.company_id
    assert missing["total"] == 1
    assert missing["items"][0]["id"] == adobe.company_id
    assert missing["items"][0]["company_opportunity_count"] == 1


def test_company_maintenance_context_groups_live_postings_and_official_sources(tools, db):
    first = seed(
        db,
        company_name="株式会社一括保守",
        event_name="27卒本選考",
        graduation_years=["27卒"],
        source_url="https://example.com/maintenance-selection",
    )
    second = seed(
        db,
        company_name="株式会社一括保守",
        event_name="サマーインターン",
        graduation_years=["28卒"],
        source_url="https://example.com/maintenance-summer",
    )
    target = call(
        "add_collection_target",
        collection_target_args(
            company_name="株式会社一括保守",
            request_id="maintenance-target-0001",
            sources=[
                {"source_type": "recruit", "url": "https://example.com/maintenance-recruit"},
                {"source_type": "internship", "url": "https://example.com/maintenance-intern"},
            ],
        ),
    )["target"]

    context = call("get_company_maintenance_context", {"company_id": first.company_id})

    assert context["company"]["id"] == first.company_id
    assert context["collection_target_id"] == target["id"]
    assert {source["url"] for source in context["official_sources"]} == {
        "https://example.com/maintenance-recruit",
        "https://example.com/maintenance-intern",
    }
    opportunities = {item["id"]: item for item in context["opportunities"]}
    assert set(opportunities) == {first.id, second.id}
    assert opportunities[first.id]["graduation_years"] == ["27卒"]
    assert opportunities[second.id]["source_url"] == "https://example.com/maintenance-summer"
    assert opportunities[second.id]["source_checked_at"] is not None
    assert tool_error("get_company_maintenance_context", {"company_id": 999999})["error"] == "not_found"


def test_collection_queue_supports_create_patch_source_management_and_checks(tools, db):
    created = call("add_collection_target", collection_target_args())
    target = created["target"]

    assert created["idempotent_replay"] is False
    assert target["company"]["name"] == "株式会社収集テスト"
    assert target["sources"][0]["url"] == "https://example.com/recruit"
    assert call("get_collection_queue", {"industry": "IT・通信"})["items"][0]["id"] == target["id"]
    assert call("get_collection_target", {"target_id": target["id"]})["id"] == target["id"]

    updated = call(
        "update_collection_target",
        {
            "target_id": target["id"],
            "payload": {
                "priority_tier": 2,
                "selection_reason": None,
                "request_id": "collection-update-0001",
                "client_name": "pytest",
            },
        },
    )
    assert updated["target"]["priority_tier"] == 2
    assert updated["target"]["selection_reason"] is None

    added_source = call(
        "add_collection_source",
        {
            "target_id": target["id"],
            "payload": {
                "source_type": "internship",
                "url": "https://example.com/internship",
                "request_id": "collection-source-0001",
                "client_name": "pytest",
            },
        },
    )["source"]
    changed_source = call(
        "update_collection_source",
        {
            "source_id": added_source["id"],
            "payload": {
                "is_active": False,
                "request_id": "collection-source-update-0001",
                "client_name": "pytest",
            },
        },
    )
    assert changed_source["source"]["is_active"] is False

    checked = call(
        "record_collection_check",
        {
            "target_id": target["id"],
            "payload": {
                "result": "no_opening",
                "source_url": "https://example.com/recruit",
                "request_id": "collection-check-0001",
                "client_name": "pytest",
            },
        },
    )
    replay = call(
        "record_collection_check",
        {
            "target_id": target["id"],
            "payload": {
                "result": "no_opening",
                "source_url": "https://example.com/recruit",
                "request_id": "collection-check-0001",
                "client_name": "pytest",
            },
        },
    )
    assert checked["target"]["last_check_result"] == "no_opening"
    assert checked["target"]["next_check_at"] is not None
    assert replay["idempotent_replay"] is True
    history = call("list_collection_checks", {"target_id": target["id"]})["items"]
    assert len(history) == 1
    assert history[0]["result"] == "no_opening"
    assert call("get_collection_queue", {})["items"] == []
    assert call("list_collection_targets", {"include_inactive": True})["total"] == 1


@pytest.mark.parametrize("is_active", [True, False])
def test_duplicate_collection_source_returns_existing_state_without_changing_it(tools, db, is_active):
    target = call("add_collection_target", collection_target_args())["target"]
    source = call(
        "add_collection_source",
        {
            "target_id": target["id"],
            "payload": {
                "source_type": "internship", "url": "https://other.example/internship",
                "request_id": "duplicate-source-create",
            },
        },
    )["source"]
    if not is_active:
        call(
            "update_collection_source",
            {"source_id": source["id"], "payload": {"is_active": False, "request_id": "duplicate-source-disable"}},
        )
    db.expire_all()
    before = call("get_collection_target", {"target_id": target["id"]})
    error = tool_error(
        "add_collection_source",
        {
            "target_id": target["id"],
            "payload": {
                "source_type": "recruit", "url": source["url"], "request_id": "duplicate-source-rejected",
            },
        },
    )["errors"][0]
    assert error["source_id"] == source["id"]
    assert error["is_active"] is is_active
    assert error["source_type"] == "internship"
    if is_active:
        assert "再利用" in error["alternative"]
    else:
        assert "公式ページであることを確認" in error["alternative"]
        assert "update_collection_source" in error["alternative"]
        assert f"source_id={source['id']}" in error["alternative"]
        assert "is_active=true" in error["alternative"]
    assert call("get_collection_target", {"target_id": target["id"]}) == before


def test_inactive_collection_source_error_guides_explicit_activation_and_recheck(tools, db):
    target = call("add_collection_target", collection_target_args())["target"]
    discovery = call(
        "record_collection_check",
        {
            "target_id": target["id"],
            "payload": {
                "result": "no_opening", "source_url": target["sources"][0]["url"],
                "discovered_sources": [{"source_type": "recruit", "url": "https://other.example/graduate"}],
                "request_id": "inactive-source-discovered",
            },
        },
    )["target"]
    source = next(source for source in discovery["sources"] if not source["is_active"])
    db.expire_all()
    before = call("get_collection_target", {"target_id": target["id"]})
    args = {
        "target_id": target["id"], "run_id": "inactive-source-recovery",
        "payload": {
            "result": "needs_review", "source_url": source["url"] + "/?utm_source=test#course",
            "request_id": "inactive-source-check-rejected",
        },
    }
    detail = tool_error("record_collection_check", args)["errors"][0]
    assert detail["source_id"] == source["id"]
    assert detail["is_active"] is False
    assert detail["source_type"] == "recruit"
    assert detail["expected"] == [target["sources"][0]["url"]]
    assert "公式ページであることを確認" in detail["alternative"]
    assert "update_collection_source" in detail["alternative"]
    assert f"source_id={source['id']}" in detail["alternative"]
    assert "is_active=true" in detail["alternative"]
    assert call("get_collection_target", {"target_id": target["id"]}) == before
    assert len(call("list_collection_checks", {"target_id": target["id"]})["items"]) == 1
    audit = call("list_recent_writes", {"run_id": args["run_id"]})
    assert audit["failed_count"] == 1
    assert audit["items"][0]["errors"][0] == detail

    call(
        "update_collection_source",
        {"source_id": detail["source_id"], "payload": {"is_active": True, "request_id": "inactive-source-enable"}},
    )
    assert len(call("list_collection_checks", {"target_id": target["id"]})["items"]) == 1
    result = call(
        "record_collection_check",
        args | {"payload": args["payload"] | {"request_id": "inactive-source-check-corrected"}},
    )
    assert result["success"] is True
    assert result["target"]["last_check_result"] == "needs_review"
    assert len(call("list_collection_checks", {"target_id": target["id"]})["items"]) == 2


def test_unregistered_collection_source_error_guides_addition(tools, db):
    target = call("add_collection_target", collection_target_args())["target"]
    detail = tool_error(
        "record_collection_check",
        {
            "target_id": target["id"],
            "payload": {
                "result": "needs_review", "source_url": "https://unknown.example/graduate",
                "request_id": "unknown-source-check-rejected",
            },
        },
    )["errors"][0]
    assert "source_id" not in detail
    assert "add_collection_source" in detail["alternative"]
    assert call("list_collection_checks", {"target_id": target["id"]})["items"] == []


def test_mcp_maintenance_surfaces_exclude_closed_postings(tools, db):
    active = seed(
        db,
        company_name="株式会社MCP保守対象",
        event_name="現行募集",
        source_url="https://example.com/mcp-maintenance-active",
    )
    closed = seed(
        db,
        company_name="株式会社MCP保守対象",
        event_name="締切済み募集",
        recruitment_status="締切",
        source_url="https://example.com/mcp-maintenance-closed",
    )
    unknown = seed(
        db,
        company_name="株式会社MCP保守対象",
        event_name="状態不明募集",
        recruitment_status="不明",
        source_url="https://example.com/mcp-maintenance-unknown",
    )
    for item in (active, closed, unknown):
        item.source_checked_at = datetime.now(timezone.utc) - timedelta(days=40)  # noqa: UP017
    db.commit()

    stale = call("list_stale_opportunities", {"days": 7})
    assert [item["id"] for item in stale["items"]] == [active.id]

    target = call(
        "add_collection_target",
        collection_target_args(
            company_name="株式会社MCP保守対象",
            request_id="mcp-maintenance-target-0001",
            sources=[{"source_type": "recruit", "url": "https://example.com/mcp-maintenance-recruit"}],
        ),
    )["target"]
    expected_ids = [active.id]
    assert [item["id"] for item in target["opportunities"]] == expected_ids
    assert [item["id"] for item in call("get_collection_target", {"target_id": target["id"]})["opportunities"]] == expected_ids
    context = call("get_company_maintenance_context", {"company_id": active.company_id})
    assert [item["id"] for item in context["opportunities"]] == expected_ids
    assert closed.id not in {item["id"] for item in context["opportunities"]}
    assert unknown.id not in {item["id"] for item in context["opportunities"]}


def test_collection_targets_reject_bad_classification_and_non_primary_sources(tools, db):
    classification = tool_error("add_collection_target", collection_target_args(sector="銀行"))
    source = tool_error(
        "add_collection_target",
        collection_target_args(
            request_id="collection-create-0002",
            sources=[{"source_type": "recruit", "url": "https://job.mynavi.jp/example"}],
        ),
    )

    assert classification["errors"][0]["field"] == "業種"
    assert source["errors"][0]["field"] == "公式情報源[0].公式情報源URL"


# --- The tool boundary: what a failing tool is allowed to tell its caller -------------------------


def test_an_unexpected_failure_never_hands_the_caller_the_sql_that_produced_it(tools, db, monkeypatch, caplog):
    """search_opportunity is anonymous, so its failure text is public.

    FastMCP stringifies whatever a tool body raises into the tool result, and MCP dispatch never
    reaches main.py's catch-all handler. A SQLAlchemy error stringifies to the whole statement plus its
    bound parameters, which is a full column listing of four tables for anyone who can make the query
    fail.
    """
    statement = (
        "SELECT opportunities.id, companies.name, company_aliases.alias, opportunity_jobs.job_id "
        "FROM opportunities JOIN companies ON companies.id = opportunities.company_id"
    )

    def explode(*_args, **_kwargs):
        raise OperationalError(statement, {"pattern": "%" + "あ" * 3000 + "%"}, Exception("too complex"))

    monkeypatch.setattr(mcp_server, "search_opportunities", explode)
    with caplog.at_level(logging.ERROR):
        with pytest.raises(ToolError) as raised:
            asyncio.run(mcp_server.mcp.call_tool("search_opportunity", {"query": "テスト"}))

    message = str(raised.value)
    assert json.loads(message[message.index("{") :]) == mcp_server.INTERNAL_ERROR
    for leaked in ("SELECT", "FROM opportunities", "company_aliases", "あ"):
        assert leaked not in message
    # The operator still gets the whole thing, with its traceback, on the server side.
    assert any(record.exc_info and "search_opportunity" in record.getMessage() for record in caplog.records)


def test_the_boundary_lets_the_intentional_json_errors_through(tools, db):
    """The guard must not flatten the structured replies agents are expected to read."""
    assert tool_error("get_opportunity", {"reference": "ZZZZZZZZ"})["error"] == "not_found"
    assert tool_error("add_opportunity", write_args(sector="銀行"))["error"] == "validation_failed"


# --- Bounds on what an unauthenticated caller can ask for -----------------------------------------


def test_anonymous_tools_bound_every_string_they_accept():
    """Anonymous inputs must be bounded before query work or datetime parsing.

    Unbounded, that is an unauthenticated way to buy an arbitrarily expensive scan, so the anonymous
    tools carry the same bounds the authenticated list_* tools already had.
    """
    listed = asyncio.run(mcp_server.mcp.list_tools())
    schemas = {tool.name: tool.inputSchema for tool in listed}

    def max_length(name: str, field: str) -> int | None:
        prop = schemas[name]["properties"][field]
        options = prop.get("anyOf") or [prop]
        lengths = [option.get("maxLength") for option in options if option.get("type") == "string"]
        return max(lengths) if lengths and all(lengths) else None

    assert max_length("search_opportunity", "query") == 200
    assert max_length("find_similar_opportunities", "company_name") == 200
    assert max_length("find_similar_opportunities", "event_name") == 200
    assert max_length("get_opportunity", "reference") == 64
    assert max_length("find_opportunities_by_source_url", "source_url") == 2048

    for name in mcp_server.ANONYMOUS_TOOLS:
        for field, prop in schemas[name]["properties"].items():
            options = prop.get("anyOf") or [prop]
            for option in options:
                if option.get("format") == "date-time":
                    assert prop.get("maxLength") == mcp_server.MAX_SEARCH_DATETIME_LENGTH
                    continue
                if option.get("type") == "string" and "enum" not in option and option.get("format") != "date-time":
                    assert option.get("maxLength"), f"{name}.{field} accepts an unbounded string"


def test_an_oversized_anonymous_query_is_refused_before_the_database_sees_it(tools, db, monkeypatch):
    def unreachable(*_args, **_kwargs):
        raise AssertionError("the search service must not be reached")

    monkeypatch.setattr(mcp_server, "search_opportunities", unreachable)
    with pytest.raises(ToolError):
        asyncio.run(mcp_server.mcp.call_tool("search_opportunity", {"query": "あ" * 201}))


def test_an_oversized_anonymous_datetime_is_refused_before_parsing(tools, db, monkeypatch):
    def unreachable(*_args, **_kwargs):
        raise AssertionError("the search service must not be reached")

    monkeypatch.setattr(mcp_server, "search_opportunities", unreachable)
    long_fraction = "2026-10-01T00:00:00." + "1" * 100_000 + "Z"
    with pytest.raises(ToolError):
        asyncio.run(mcp_server.mcp.call_tool("search_opportunity", {"created_at_after": long_fraction}))


# --- ADR-0002: every rejected write is audited ----------------------------------------------------


def patch_args(item, updated_at, **overrides) -> dict:
    return {
        "opportunity_id": item.id,
        "changes": {"description": "監査ログ確認のために内容を書き換えます。"},
        "expected_updated_at": updated_at,
        "request_id": "patch-audit-0001",
        "client_name": "pytest",
    } | overrides


def failed_audit(db, request_id: str) -> AuditLog:
    return db.query(AuditLog).filter_by(request_id=request_id, success=False).one()


def test_every_patch_failure_branch_leaves_an_audit_row(tools, db):
    """ADR-0002 audits failures, and patch used to record only the pydantic branch.

    The optimistic-lock conflict, the fixed-value rejection and the empty-diff rejection all raised the
    client reply and wrote nothing, so the identical failure was auditable on update_opportunity and
    invisible on patch_opportunity.
    """
    item = seed(db)
    stale = call("get_opportunity", {"reference": item.id})["updated_at"]
    fresh = call("patch_opportunity", patch_args(item, stale))["opportunity"]["updated_at"]

    conflict = tool_error("patch_opportunity", patch_args(item, stale, request_id="patch-audit-stale-0001"))
    fixed_value = tool_error(
        "patch_opportunity",
        patch_args(item, fresh, changes={"sector": "銀行"}, request_id="patch-audit-sector-0001"),
    )
    unchanged = tool_error(
        "patch_opportunity",
        patch_args(
            item,
            fresh,
            changes={"description": "監査ログ確認のために内容を書き換えます。"},
            request_id="patch-audit-nochange-0001",
        ),
    )
    broken_type = tool_error(
        "patch_opportunity",
        patch_args(item, fresh, changes={"deadline": "来週まで"}, request_id="patch-audit-type-0001"),
    )

    assert conflict["errors"][0]["field"] == "更新前の最終確認日時"
    assert fixed_value["errors"][0]["field"] == "業種"
    assert "変わる項目がありません" in unchanged["errors"][0]["reason"]
    assert broken_type["errors"][0]["field"] == "締め切り"
    for request_id in (
        "patch-audit-stale-0001",
        "patch-audit-sector-0001",
        "patch-audit-nochange-0001",
        "patch-audit-type-0001",
    ):
        assert failed_audit(db, request_id).action == "patch"


def test_the_read_only_preview_tools_do_not_append_to_the_audit_log(tools, db):
    """readOnlyHint=True is kept honest instead of being corrected.

    Both tools exist to be retried while an agent converges on a valid payload, so persisting each
    attempt would let a well-behaved client grow audit_logs without ever writing anything. The
    repeated-failure signal still comes from the Redis counter behind _validation_error.
    """
    item = seed(db)
    current = call("get_opportunity", {"reference": item.id})["updated_at"]
    before = db.query(AuditLog).count()

    tool_error(
        "preview_opportunity_patch",
        patch_args(item, current, changes={"sector": "銀行"}, request_id="preview-audit-0001"),
    )
    tool_error(
        "preview_opportunity_patch",
        patch_args(item, current, changes={"deadline": "来週まで"}, request_id="preview-audit-0002"),
    )
    tool_error("validate_opportunity", write_args(sector="銀行", request_id="validate-audit-0001"))
    tool_error("validate_opportunity", write_args(deadline="来週まで", request_id="validate-audit-0002"))

    assert db.query(AuditLog).count() == before


# --- Idempotency the caller can actually see ------------------------------------------------------


def test_upsert_reports_a_replay_instead_of_claiming_a_second_create(tools, db):
    """A retry after a timeout must not read as "created" twice.

    upsert_opportunity dropped write_opportunity's replayed flag and MCPUpsertResponse had no field to
    carry it, so an agent resending the same request_id believed it had registered two postings.
    """
    arguments = write_args(request_id="upsert-replay-0001")

    created = call("upsert_opportunity", arguments)
    replayed = call("upsert_opportunity", arguments)

    assert created["result"] == "created"
    assert created["idempotent_replay"] is False
    assert replayed["idempotent_replay"] is True
    assert replayed["opportunity"]["id"] == created["opportunity"]["id"]
    assert db.query(Opportunity).count() == 1


def test_request_ids_that_differ_only_in_whitespace_are_one_operation(tools, db):
    """The inline request_id declarations lacked strip_whitespace, so "req-1 " retried as a new write."""
    item = seed(db)
    preview = call("preview_delete_opportunity", {"opportunity_id": item.id})
    arguments = {
        "opportunity_id": item.id,
        "expected_updated_at": preview["expected_updated_at"],
        "request_id": "delete-whitespace-0001",
        "client_name": "pytest",
    }

    first = call("delete_opportunity", arguments)
    retried = call("delete_opportunity", arguments | {"request_id": " delete-whitespace-0001 "})

    assert first["idempotent_replay"] is False
    assert retried["idempotent_replay"] is True


def test_every_write_tool_declares_the_shared_request_id_and_client_name_types():
    listed = asyncio.run(mcp_server.mcp.list_tools())
    schemas = {tool.name: tool.inputSchema for tool in listed}

    for name in (
        "preview_opportunity_patch",
        "patch_opportunity",
        "update_recruitment_status",
        "verify_opportunity",
        "delete_opportunity",
        "restore_opportunity",
        "add_company_alias",
        "delete_company_alias",
        "merge_company",
    ):
        request_id = schemas[name]["properties"]["request_id"]
        client_name = schemas[name]["properties"]["client_name"]
        assert (request_id["minLength"], request_id["maxLength"]) == (8, 100), name
        assert (client_name["minLength"], client_name["maxLength"]) == (1, 100), name


# --- One source of truth for who may call what ----------------------------------------------------


def test_every_authenticated_tool_says_so_in_its_description():
    """ANONYMOUS_TOOLS, the description text and main.py's gate are three places that can disagree.

    The gate is exercised elsewhere; this keeps the text an agent reads from drifting away from the set
    that actually decides.
    """
    listed = asyncio.run(mcp_server.mcp.list_tools())

    for tool in listed:
        requires_auth = tool.name not in mcp_server.ANONYMOUS_TOOLS
        assert ("認証が必要です" in tool.description) == requires_auth, tool.name


# --- Fixed values the write path will actually accept ---------------------------------------------


class FakeRedis:
    """Just the two commands master_payload uses. The test environment has no Redis."""

    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def setex(self, key: str, _ttl: int, value: str) -> None:
        self.store[key] = value


def _drop_alembic_version(db) -> None:
    db.rollback()
    db.execute(text("DROP TABLE IF EXISTS alembic_version"))
    db.commit()


def test_get_master_values_stops_advertising_fixed_values_the_write_path_rejects(tools, db, monkeypatch, request):
    """The cache was a single key with a one-hour TTL and no reachable invalidation.

    Master rows only ever change in a migration, and for up to an hour afterwards get_master_values
    served the old list while validate_write read the new rows directly - it offered values that
    add_opportunity rejected, and hid the ones it had just gained. Keying the payload on the applied
    schema revision rotates it in the same step that can change the data.
    """
    fake = FakeRedis()
    # alembic_version is not part of Base.metadata, so the db fixture's drop_all() will not remove it.
    # On the in-memory SQLite the whole database goes away regardless, but against the PostgreSQL job
    # the table would survive into the next run and this CREATE would fail with DuplicateTable.
    db.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
    db.execute(text("INSERT INTO alembic_version (version_num) VALUES ('20260726_0001')"))
    db.commit()
    request.addfinalizer(lambda: _drop_alembic_version(db))

    monkeypatch.setattr(master_cache, "redis_client", lambda: fake)
    first = call("get_master_values", {})

    # Same revision: the payload is genuinely cached, so a row added behind the cache stays unseen.
    db.add(Industry(id=900, slug="industry-90", name="架空業界", sort_order=900, is_active=True))
    db.commit()
    assert call("get_master_values", {}) == first

    # The migration that seeds a master value moves the revision, which rotates the key.
    db.execute(text("UPDATE alembic_version SET version_num = '20260920_9999'"))
    db.commit()
    refreshed = call("get_master_values", {})

    assert "架空業界" not in [industry["name"] for industry in first["industries"]]
    assert "架空業界" in [industry["name"] for industry in refreshed["industries"]]
    assert len(fake.store) == 2, "the superseded generation is left to expire rather than deleted"


def test_maintenance_tools_explain_individual_sources_and_incremental_saving():
    listed = {tool.name: tool for tool in asyncio.run(mcp_server.mcp.list_tools())}
    check = listed["record_collection_check"]
    fields = check.inputSchema["properties"]["payload"]["properties"]
    assert "登録済み" in fields["result"]["description"]
    assert "先にadd_opportunity" in fields["result"]["description"]
    assert "採用トップページで代用できません" in fields["source_url"]["description"]
    assert "実際に確認" in fields["source_url"]["description"]
    assert "foundの場合だけ" in fields["opportunity_id"]["description"]
    assert "全社の調査完了まで保存を待たない" in check.description
    assert "source_id・is_active・source_type" in check.description
    assert "無効な情報源として追加" in check.description
    assert "update_collection_source" in listed["add_collection_source"].description
    assert "有効化だけでは確認記録は保存されません" in listed["update_collection_source"].description
    assert "全社の調査完了まで保存を待たない" in listed["get_collection_queue"].description
    assert "少数社" in mcp_server.mcp.instructions[:512]
    assert "run_id" in mcp_server.mcp.instructions[:512]


def test_all_write_tools_publish_an_optional_bounded_run_id():
    for tool in asyncio.run(mcp_server.mcp.list_tools()):
        if tool.annotations.readOnlyHint:
            continue
        schema = tool.inputSchema
        assert "run_id" not in schema.get("required", [])
        field = schema["properties"]["run_id"]
        string = next(option for option in field["anyOf"] if option["type"] == "string")
        assert (string["minLength"], string["maxLength"]) == (8, 100)


@pytest.mark.parametrize("run_id", ["short", "x" * 101])
def test_invalid_run_id_is_rejected_before_writing(tools, db, run_id):
    with pytest.raises(ToolError):
        call("add_opportunity", write_args() | {"run_id": run_id})
    assert db.scalar(select(Opportunity.id)) is None
    assert db.scalar(select(AuditLog.id)) is None


def test_collection_url_error_can_be_corrected_without_false_confirmation(tools, db):
    def confirmation_time(value):
        return datetime.fromisoformat(value).replace(tzinfo=UTC) if value else None

    target = call("add_collection_target", collection_target_args())["target"]
    item = call(
        "add_opportunity",
        write_args(company_name=target["company"]["name"], source_url="https://example.com/recruit/posting"),
    )["opportunity"]
    checked_before = confirmation_time(item["source_checked_at"])
    target_before = confirmation_time(call("get_collection_target", {"target_id": target["id"]})["last_checked_at"])
    args = {
        "target_id": target["id"],
        "run_id": "run-check-url-mismatch",
        "payload": {
            "result": "found", "opportunity_id": item["id"], "source_url": "https://example.com/recruit",
            "request_id": "check-mismatch-run-0001",
        },
    }
    error = tool_error("record_collection_check", args)
    detail = error["errors"][0]
    assert detail["expected"] == item["source_url"]
    assert "実際に確認" in detail["alternative"]
    assert "opportunity_idを省略" in detail["alternative"]
    assert "needs_review" in detail["alternative"]
    assert "URLだけを差し替えて" in detail["alternative"]
    assert confirmation_time(call("get_opportunity", {"reference": item["id"]})["source_checked_at"]) == checked_before
    assert confirmation_time(call("get_collection_target", {"target_id": target["id"]})["last_checked_at"]) == target_before
    result = call(
        "record_collection_check",
        args | {"payload": {
            "result": "needs_review", "source_url": "https://example.com/recruit",
            "request_id": "check-corrected-run-0002",
        }},
    )
    assert result["success"] is True
    assert confirmation_time(call("get_opportunity", {"reference": item["id"]})["source_checked_at"]) == checked_before
    history = call("list_recent_writes", {"run_id": args["run_id"]})
    assert (history["total_count"], history["succeeded_count"], history["failed_count"]) == (2, 1, 1)


def test_run_history_isolates_runs_and_counts_rejections_and_side_effects(tools):
    run_id = "run-maintenance-first"
    call("add_collection_target", collection_target_args() | {"run_id": run_id})
    args = write_args(company_name="株式会社収集テスト", source_url="https://example.com/recruit/posting")
    call("add_opportunity", args | {"run_id": run_id})
    tool_error("add_opportunity", write_args(sector="銀行", request_id="run-rejected-0001") | {"run_id": run_id})
    call("add_opportunity", args | {"run_id": "run-maintenance-retry"})
    call("add_opportunity", write_args(company_name="実行IDなし企業", request_id="untracked-run-0001"))
    history = call("list_recent_writes", {"run_id": run_id, "limit": 1})
    assert (history["total_count"], history["succeeded_count"], history["failed_count"]) == (4, 3, 1)
    assert history["unknown_count"] == 0
    assert len(history["items"]) == 1
    assert history["has_more"] is True
    assert history["items"][0]["run_id"] == run_id
    assert call("list_recent_writes", {"run_id": "run-maintenance-retry"})["total_count"] == 0
    untracked = call("list_recent_writes", {"limit": 1})["items"][0]
    assert untracked["run_id"] is None
    opportunities = call("list_recent_writes", {"run_id": run_id, "entity_type": "opportunity"})
    assert (opportunities["total_count"], opportunities["succeeded_count"], opportunities["failed_count"]) == (2, 1, 1)
    assert call("list_recent_writes", {"run_id": run_id, "client_name": "nobody"})["total_count"] == 0
    assert call("list_recent_writes", {"run_id": "run-unknown-value"})["items"] == []


def test_run_id_keeps_legacy_request_hashes_compatible(tools):
    args = collection_target_args()
    original = call("add_collection_target", args)
    replay = call("add_collection_target", args | {"run_id": "run-legacy-retry"})
    assert replay["idempotent_replay"] is True
    assert replay["target"]["id"] == original["target"]["id"]
    assert call("list_recent_writes", {"run_id": "run-legacy-retry"})["items"] == []


def test_run_history_pages_cover_every_record_and_counts_do_not_truncate(tools, db):
    db.add_all([
        AuditLog(action="verify", entity_type="opportunity", request_id=f"run-page-{i:04}",
                 client_name="history-test", run_id="run-over-100-records", success=i % 2 == 0)
        for i in range(105)
    ])
    db.commit()
    first = call("list_recent_writes", {"run_id": "run-over-100-records", "limit": 100})
    second = call("list_recent_writes", {"run_id": "run-over-100-records", "limit": 100, "page": 2})
    assert (first["total_count"], first["succeeded_count"], first["failed_count"]) == (105, 53, 52)
    assert second["total_count"] == first["total_count"]
    assert len(first["items"]) == 100 and len(second["items"]) == 5
    assert first["has_more"] is True and second["has_more"] is False
    assert len({row["request_id"] for row in first["items"] + second["items"]}) == 105


def test_review_queue_excludes_expired_before_limit_and_keeps_today_and_undated(tools, db, monkeypatch):
    fixed_now = datetime(2026, 10, 3, 16, 0, tzinfo=UTC)  # October 4 in Tokyo.

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now.astimezone(tz) if tz else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr("app.services.opportunities.datetime", FrozenDateTime)
    for index in range(3):
        item = seed(db, company_name=f"期限超過企業{index}", event_name=f"期限超過{index}",
                    deadline="2026-10-03", source_url=f"https://example.com/expired/{index}")
        item.source_checked_at = fixed_now
    current = seed(db, company_name="当日企業", event_name="当日募集", deadline="2026-10-04",
                   event_end_date="2026-10-04", source_url="https://example.com/today")
    current.source_checked_at = fixed_now - timedelta(days=30)
    undated = seed(db, company_name="日付未設定企業", event_name="日付未設定募集", deadline=None,
                   event_end_date=None, source_url="https://example.com/undated")
    undated.source_checked_at = fixed_now - timedelta(days=20)
    db.commit()
    default = call("list_stale_opportunities", {"limit": 1})
    assert default["items"][0]["review_reasons"] == ["deadline_passed_while_open"]
    filtered = call("list_stale_opportunities", {"limit": 1, "exclude_expired": True})
    assert filtered["items"][0]["id"] == current.id
    assert {row["id"] for row in call("list_stale_opportunities", {"exclude_expired": True})["items"]} == {
        current.id, undated.id,
    }
