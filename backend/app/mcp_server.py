import json
from typing import Any
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import ValidationError

from app.config import get_settings
from app.db import SessionLocal
from app.schemas import MCPUpdateRequest, MCPWriteRequest
from app.services.errors import pydantic_errors
from app.services.master_cache import master_payload
from app.services.opportunities import (
    DomainValidationError,
    record_failed_attempt,
    search_opportunities,
    write_opportunity,
)
from app.services.rate_limit import (
    RateLimitExceeded,
    RateLimitUnavailable,
    enforce_rate_limit,
    register_validation_failure,
)
from app.services.serialization import opportunity_dict

settings = get_settings()
public_url = urlsplit(settings.mcp_public_url)
public_host = public_url.hostname

allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
if public_host:
    allowed_hosts.extend([public_host, f"{public_host}:*"])

mcp = FastMCP(
    "All Job",
    instructions=(
        "日本のインターン・本選考情報を検索・登録・更新するMCPです。"
        "追加・更新の前にget_master_valuesで固定値を確認してください。"
        "日付はYYYY-MM-DD、URLはhttpsを使用し、推測できない任意項目はnullにしてください。"
    ),
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
            settings.issuer,
        ],
    ),
)


def _json_error(payload: dict[str, Any]) -> ToolError:
    return ToolError(json.dumps(payload, ensure_ascii=False, default=str))


def _rate_limit(client_name: str, operation: str) -> None:
    try:
        enforce_rate_limit(client_name, operation)
    except RateLimitExceeded as exc:
        raise _json_error(
            {
                "error": "rate_limit_exceeded",
                "message": "1分あたりの操作上限を超えました。時間をおいて再試行してください。",
            }
        ) from exc
    except RateLimitUnavailable as exc:
        raise _json_error(
            {
                "error": "write_temporarily_unavailable",
                "message": "入力制御サービスに接続できないため、安全のため書き込みを停止しています。",
            }
        ) from exc


@mcp.tool(description="登録済みの募集情報をキーワード・固定値で検索します。ログインは不要です。")
def search_opportunity(
    query: str | None = None,
    recruitment_status: list[str] | None = None,
    industry: list[str] | None = None,
    event_type: list[str] | None = None,
    job_category: list[str] | None = None,
    graduation_year: list[str] | None = None,
    sort: str = "deadline",
    page: int = 1,
) -> dict[str, Any]:
    with SessionLocal() as db:
        result = search_opportunities(
            db,
            q=query,
            status=recruitment_status,
            industry=industry,
            event_type=event_type,
            job_category=job_category,
            graduation_year=graduation_year,
            sort=sort if sort in {"deadline", "updated", "created"} else "deadline",
            page=max(1, page),
            per_page=20,
        )
        return {
            "items": [opportunity_dict(item) for item in result.items],
            "total": result.total,
            "page": result.page,
            "total_pages": result.total_pages,
        }


@mcp.tool(description="登録・更新で選択できる固定値マスタを返します。書き込み前に必ず確認してください。")
def get_master_values() -> dict[str, Any]:
    with SessionLocal() as db:
        return master_payload(db)


def _perform_write(raw: dict[str, Any], opportunity_id: str | None = None) -> dict[str, Any]:
    action = "update" if opportunity_id else "create"
    request_id = raw.get("request_id")
    client_name = raw.get("client_name") or "mcp-client"
    _rate_limit(client_name, action)
    model = MCPUpdateRequest if opportunity_id else MCPWriteRequest
    try:
        request = model.model_validate(raw)
    except ValidationError as exc:
        errors = pydantic_errors(exc, raw)
        with SessionLocal() as db:
            record_failed_attempt(
                db,
                action=action,
                request_id=request_id,
                client_name=client_name,
                source_url=raw.get("source_url"),
                errors=errors,
            )
        attempts = register_validation_failure(client_name, request_id or "missing")
        raise _json_error(
            {
                "error": "validation_failed",
                "message": (
                    "検証エラーが3回続きました。推測で補わず、任意項目をnullにするか登録を見送ってください。"
                    if attempts >= 3
                    else "入力内容を修正して再試行してください。"
                ),
                "attempt": attempts,
                "errors": errors,
            }
        ) from exc

    write_data = request.model_dump(exclude={"request_id", "client_name"})
    from app.schemas import OpportunityInput

    data = OpportunityInput.model_validate(write_data)
    try:
        with SessionLocal() as db:
            item, replayed = write_opportunity(
                db,
                data=data,
                request_id=request.request_id,
                client_name=request.client_name,
                opportunity_id=opportunity_id,
            )
            return {
                "success": True,
                "idempotent_replay": replayed,
                "message": "募集情報を更新しました" if opportunity_id else "募集情報を登録しました",
                "opportunity": opportunity_dict(item),
            }
    except DomainValidationError as exc:
        with SessionLocal() as db:
            record_failed_attempt(
                db,
                action=action,
                request_id=request.request_id,
                client_name=request.client_name,
                source_url=request.source_url,
                errors=exc.errors,
            )
        attempts = register_validation_failure(request.client_name, request.request_id)
        raise _json_error(
            {
                "error": "validation_failed",
                "message": (
                    "検証エラーが3回続きました。未入力での登録または登録の見送りを検討してください。"
                    if attempts >= 3
                    else "固定値を確認して再試行してください。"
                ),
                "attempt": attempts,
                "errors": exc.errors,
            }
        ) from exc
    except LookupError as exc:
        raise _json_error({"error": "not_found", "message": "指定された募集情報が見つかりません"}) from exc


@mcp.tool(
    description=(
        "募集情報を1件追加します。request_idはクライアント側で一意にし、再試行時は同じ値を使用してください。"
        "payload内の固定値はget_master_valuesのnameを指定します。"
    )
)
def add_opportunity(payload: MCPWriteRequest) -> dict[str, Any]:
    return _perform_write(payload.model_dump(mode="json"))


@mcp.tool(
    description=(
        "既存の募集情報を全項目置換で更新します。部分更新は行わず、現在値を検索してから完全なpayloadを送ってください。"
    )
)
def update_opportunity(opportunity_id: str, payload: MCPUpdateRequest) -> dict[str, Any]:
    return _perform_write(payload.model_dump(mode="json"), opportunity_id=opportunity_id)


def mcp_http_app():
    return mcp.streamable_http_app()
