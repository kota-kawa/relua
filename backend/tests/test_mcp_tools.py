"""What an external client such as ChatGPT actually receives from the MCP surface."""

import asyncio
import json
from datetime import date, timedelta

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from app import mcp_server
from app.schemas import OpportunityInput
from app.services import rate_limit
from app.services.opportunities import write_opportunity
from tests.test_validation import valid_payload


@pytest.fixture
def tools(db, monkeypatch):
    """Point the tool layer at the test session and take Redis out of the path.

    The tools open their own sessions through SessionLocal, which no dependency override reaches,
    and the rate limiter refuses writes outright when Redis is unreachable.
    """

    class Sessions:
        def __call__(self):
            return self

        def __enter__(self):
            return db

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(mcp_server, "SessionLocal", Sessions())
    monkeypatch.setattr(mcp_server, "enforce_rate_limit", lambda client_name, operation: None)
    monkeypatch.setattr(rate_limit, "register_validation_failure", lambda client_name, request_id: 1)
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
        "validate_opportunity",
        "add_opportunity",
        "update_opportunity",
        "update_recruitment_status",
        "list_recent_writes",
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


def test_search_filters_publish_their_allowed_values():
    listed = asyncio.run(mcp_server.mcp.list_tools())
    properties = {tool.name: tool.inputSchema["properties"] for tool in listed}["search_opportunity"]

    assert properties["sort"]["enum"] == ["deadline", "updated", "created"]
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
        "page",
        "per_page",
    }
    assert all(properties[name].get("description") for name in properties)


def test_write_payload_schema_documents_its_fixed_values_and_rules():
    listed = asyncio.run(mcp_server.mcp.list_tools())
    payload = {tool.name: tool.inputSchema for tool in listed}["add_opportunity"]["properties"]["payload"]

    assert payload["properties"]["industry"]["enum"][0] == "IT・通信"
    assert "get_sectors" in payload["properties"]["sector"]["description"]
    assert payload["properties"]["request_id"]["minLength"] == 8
    assert payload["required"] == sorted(payload["required"], key=payload["required"].index)
    assert all("description" in field for field in payload["properties"].values())


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


def test_update_recruitment_status_touches_only_the_status_and_deadline(tools, db):
    item = seed(db)
    new_deadline = (date.today() + timedelta(days=60)).isoformat()

    result = call(
        "update_recruitment_status",
        {
            "opportunity_id": item.id,
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


def test_update_recruitment_status_replays_instead_of_writing_twice(tools, db):
    item = seed(db)
    arguments = {
        "opportunity_id": item.id,
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
            "recruitment_status": "締切",
            "deadline": "2026/09/01",
            "request_id": "status-bad-date-0001",
        },
    )

    assert error["errors"][0]["field"] == "締め切り"
    assert tool_error(
        "update_recruitment_status",
        {"opportunity_id": "missing", "recruitment_status": "締切", "request_id": "status-missing-0001"},
    )["error"] == "not_found"


def test_list_recent_writes_reports_successes_and_failures(tools, db):
    seed(db)
    tool_error("add_opportunity", write_args(request_id="history-fail-0001", event_name="別の募集", sector="銀行"))

    history = call("list_recent_writes", {"limit": 10})["items"]

    assert [entry["success"] for entry in history] == [False, True]
    assert history[0]["errors"][0]["field"] == "業種"
    assert history[1]["url"].endswith("/opportunities/" + call("search_opportunity", {})["items"][0]["public_code"])
    assert call("list_recent_writes", {"client_name": "nobody"})["items"] == []
