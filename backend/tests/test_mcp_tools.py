"""What an external client such as ChatGPT actually receives from the MCP surface."""

import asyncio
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from app import mcp_server
from app.dates import today_in_tokyo
from app.models import AuditLog, Opportunity
from app.schemas import OpportunityInput
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
        expected = [{"type": "noauth"}] if name in mcp_server.ANONYMOUS_TOOLS else [{"type": "oauth2", "scopes": ["mcp"]}]
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
    assert tools["set_company_industries"]["annotations"]["idempotentHint"] is True
    assert tools["delete_company_alias"]["annotations"]["destructiveHint"] is True
    assert tools["merge_company"]["annotations"]["destructiveHint"] is True


def test_search_filters_publish_their_allowed_values():
    listed = asyncio.run(mcp_server.mcp.list_tools())
    properties = {tool.name: tool.inputSchema["properties"] for tool in listed}["search_opportunity"]

    assert properties["sort"]["enum"] == ["relevance", "deadline", "updated", "created"]
    assert properties["sort"]["default"] == "relevance"
    assert "募集中" in properties["recruitment_status"]["anyOf"][0]["items"]["enum"]
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
    assert audit.changes["after"] == {"source_checked_at": checked_at.isoformat()}


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
    assert schemas["record_collection_check"]["properties"]["payload"]["properties"]["result"]["enum"] == [
        "found",
        "no_opening",
        "unreachable",
        "needs_review",
    ]
    check_payload = schemas["record_collection_check"]["properties"]["payload"]
    assert {"result", "source_url", "request_id"}.issubset(check_payload["required"])
    assert "実際に確認" in check_payload["properties"]["source_url"]["description"]


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
    assert source["errors"][0]["field"] == "公式情報源"
