import json
from datetime import date
from typing import Annotated, Any
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Tool as MCPTool
from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from app.config import get_settings
from app.db import SessionLocal
from app.schemas import (
    DegreeValue,
    EventFormatValue,
    EventTypeValue,
    GraduationYearValue,
    IndustryValue,
    JobCategoryValue,
    MastersResponse,
    MCPDuplicateResponse,
    MCPSearchResponse,
    MCPSectorsResponse,
    MCPUpdateRequest,
    MCPValidationResponse,
    MCPWriteHistoryResponse,
    MCPWriteRequest,
    MCPWriteResponse,
    OpportunityInput,
    OpportunityResponse,
    RecruitmentStatusValue,
    SortValue,
    UpdatePayload,
    WritePayload,
)
from app.services.errors import pydantic_errors
from app.services.master_cache import master_payload
from app.services.masters import sectors_for_industry
from app.services.opportunities import (
    DomainValidationError,
    find_exact_duplicates,
    find_similar_opportunities,
    get_opportunity_by_public_ref,
    recent_write_logs,
    record_failed_attempt,
    search_opportunities,
    update_recruitment_status,
    validate_write,
    write_opportunity,
)
from app.services.rate_limit import (
    RateLimitExceeded,
    RateLimitUnavailable,
    enforce_rate_limit,
    register_validation_failure,
)
from app.services.serialization import master_dict, opportunity_dict, opportunity_summary

settings = get_settings()
public_url = urlsplit(settings.mcp_public_url)
public_host = public_url.hostname

allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
if public_host:
    allowed_hosts.extend([public_host, f"{public_host}:*"])

#: Tools a client may call before it has logged in. Reading relua is public, writing is not.
#: main.py gates the unauthenticated transport on this same set, so the two never drift apart.
ANONYMOUS_TOOLS = frozenset(
    {
        "search_opportunity",
        "get_opportunity",
        "get_master_values",
        "get_sectors",
        "find_similar_opportunities",
    }
)

mcp = FastMCP(
    "All Job",
    instructions=(
        "日本のインターン・本選考情報を検索・登録・更新するMCPです。"
        "検索はsearch_opportunityで概要を取り、全文が必要な1件はget_opportunityで取得します。"
        "追加・更新の前にget_master_valuesとget_sectorsで固定値を確認し、"
        "同じ募集が登録済みでないかfind_similar_opportunitiesで確かめてください。"
        "自信がない入力はvalidate_opportunityで先に検証できます。"
        "締切など状況だけを直す場合はupdate_recruitment_statusを使い、全項目の再送は避けてください。"
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
            "https://chatgpt.com",
            "https://chat.openai.com",
        ],
    ),
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
#: A create is idempotent through request_id, and it never overwrites an existing record.
APPEND_ONLY = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
#: A full replacement drops any field the caller omits, which is destructive in the MCP sense.
REPLACING = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)


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


def _validation_error(client_name: str, request_id: str | None, errors: list[dict[str, Any]]) -> ToolError:
    attempts = register_validation_failure(client_name, request_id or "missing")
    return _json_error(
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
    )


def _parse_payload(raw: dict[str, Any], model: type[MCPWriteRequest] | type[MCPUpdateRequest]) -> Any:
    """Validate the payload here rather than at the tool boundary.

    FastMCP validates typed parameters before the function body runs, and answers a failure with a raw
    pydantic message. Taking the payload as a dict keeps the published JSON Schema intact while the
    errors an agent sees stay in the structured field/expected/example/alternative shape.
    """
    action = "update" if model is MCPUpdateRequest else "create"
    request_id = raw.get("request_id") if isinstance(raw, dict) else None
    client_name = (raw.get("client_name") if isinstance(raw, dict) else None) or "mcp-client"
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        errors = pydantic_errors(exc, raw)
        with SessionLocal() as db:
            record_failed_attempt(
                db,
                action=action,
                request_id=request_id,
                client_name=client_name,
                source_url=raw.get("source_url") if isinstance(raw, dict) else None,
                errors=errors,
            )
        raise _validation_error(client_name, request_id, errors) from exc


def _domain_error(request: Any, action: str, exc: DomainValidationError) -> ToolError:
    with SessionLocal() as db:
        record_failed_attempt(
            db,
            action=action,
            request_id=request.request_id,
            client_name=request.client_name,
            source_url=getattr(request, "source_url", None),
            errors=exc.errors,
        )
    return _validation_error(request.client_name, request.request_id, exc.errors)


def _write_input(request: MCPWriteRequest | MCPUpdateRequest) -> OpportunityInput:
    return OpportunityInput.model_validate(request.model_dump(exclude={"request_id", "client_name"}))


@mcp.tool(
    title="募集情報を検索",
    description=(
        "登録済みの募集情報をキーワードと固定値で検索し、概要の一覧を返します。ログインは不要です。"
        "説明文は冒頭のみ返るため、全文が必要な1件はget_opportunityで取得してください。"
    ),
    annotations=READ_ONLY,
)
def search_opportunity(
    query: Annotated[
        str | None,
        Field(description="企業名・イベント名・内容・募集要件に対する部分一致キーワード。"),
    ] = None,
    recruitment_status: Annotated[list[RecruitmentStatusValue] | None, Field(description="募集状況で絞り込みます。")] = None,
    industry: Annotated[list[IndustryValue] | None, Field(description="業界で絞り込みます。")] = None,
    sector: Annotated[
        list[str] | None,
        Field(description="業種名で絞り込みます。候補はget_sectorsで取得できます。業界と併用すると、その業界の中だけを絞り込みます。"),
    ] = None,
    event_type: Annotated[list[EventTypeValue] | None, Field(description="募集の種別で絞り込みます。")] = None,
    event_format: Annotated[list[EventFormatValue] | None, Field(description="開催形式で絞り込みます。")] = None,
    job_category: Annotated[list[JobCategoryValue] | None, Field(description="対象職種で絞り込みます。")] = None,
    graduation_year: Annotated[list[GraduationYearValue] | None, Field(description="対象卒業年で絞り込みます。")] = None,
    degree: Annotated[list[DegreeValue] | None, Field(description="対象学位で絞り込みます。")] = None,
    sort: Annotated[
        SortValue,
        Field(description="deadline=締切が近い順（締切なしは末尾）、updated=更新が新しい順、created=登録が新しい順。"),
    ] = "deadline",
    page: Annotated[int, Field(ge=1, description="1から始まるページ番号。")] = 1,
    per_page: Annotated[int, Field(ge=1, le=50, description="1ページあたりの件数（1〜50）。")] = 20,
) -> MCPSearchResponse:
    with SessionLocal() as db:
        result = search_opportunities(
            db,
            q=query,
            status=recruitment_status,
            industry=industry,
            sector=sector,
            event_type=event_type,
            event_format=event_format,
            job_category=job_category,
            graduation_year=graduation_year,
            degree=degree,
            sort=sort,
            page=page,
            per_page=per_page,
        )
        return MCPSearchResponse.model_validate(
            {
                "items": [opportunity_summary(item) for item in result.items],
                "total": result.total,
                "page": result.page,
                "per_page": result.per_page,
                "total_pages": result.total_pages,
            }
        )


@mcp.tool(
    title="募集情報を1件取得",
    description=(
        "IDまたは公開コードで募集情報を1件、全項目つきで取得します。ログインは不要です。"
        "update_opportunityは全項目置換のため、更新前に必ずこのツールで現在値を取得してください。"
    ),
    annotations=READ_ONLY,
)
def get_opportunity(
    reference: Annotated[
        str,
        Field(description="募集情報のid（UUID）または公開コード（8文字）。検索結果のid・public_codeをそのまま渡せます。"),
    ],
) -> OpportunityResponse:
    with SessionLocal() as db:
        item = get_opportunity_by_public_ref(db, reference)
        if item is None:
            raise _json_error(
                {
                    "error": "not_found",
                    "message": "指定された募集情報が見つかりません",
                    "received": reference,
                }
            )
        return OpportunityResponse.model_validate(opportunity_dict(item))


@mcp.tool(
    title="固定値マスタを取得",
    description="登録・更新で選択できる固定値マスタを全件返します。書き込み前に必ず確認してください。",
    annotations=READ_ONLY,
)
def get_master_values() -> MastersResponse:
    with SessionLocal() as db:
        return MastersResponse.model_validate(master_payload(db))


@mcp.tool(
    title="業界配下の業種を取得",
    description=(
        "指定した業界に属する業種の一覧を返します。業種は業界と一致していないと登録に失敗するため、"
        "業界を決めたあとにこのツールで候補を絞ってください。"
    ),
    annotations=READ_ONLY,
)
def get_sectors(
    industry: Annotated[IndustryValue, Field(description="業界名の固定値。", examples=["IT・通信"])],
) -> MCPSectorsResponse:
    with SessionLocal() as db:
        item, sectors = sectors_for_industry(db, industry)
        if item is None:
            raise _json_error({"error": "not_found", "message": "指定された業界が見つかりません", "received": industry})
        return MCPSectorsResponse.model_validate(
            {"industry": master_dict(item), "sectors": [master_dict(sector) for sector in sectors]}
        )


@mcp.tool(
    name="find_similar_opportunities",
    title="同じ企業の登録済み募集を探す",
    description=(
        "同じ企業の登録済み募集を探します。企業名は表記ゆれを吸収して照合します。"
        "add_opportunityの前に実行し、既に登録されているものを二重登録しないでください。"
    ),
    annotations=READ_ONLY,
)
def find_similar_opportunities_tool(
    company_name: Annotated[str, Field(description="企業名。「(株)」などの表記ゆれは吸収されます。", examples=["株式会社リルア"])],
    event_name: Annotated[
        str | None,
        Field(description="イベント名。指定すると部分一致で絞り込みます。省略するとその企業の全件を返します。"),
    ] = None,
) -> MCPDuplicateResponse:
    with SessionLocal() as db:
        matches = find_similar_opportunities(db, company_name=company_name, event_name=event_name)
        return MCPDuplicateResponse.model_validate(
            {
                "message": (
                    "既存の登録は見つかりませんでした。新規登録できます。"
                    if not matches
                    else "同じ企業の登録が見つかりました。同一の募集ならupdate_opportunityで更新してください。"
                ),
                "matches": [opportunity_summary(item) for item in matches],
            }
        )


@mcp.tool(
    title="登録内容を検証（書き込みなし）",
    description=(
        "payloadを保存せずに検証し、固定値の誤りと重複の疑いを返します。"
        "検証に失敗しても登録は行われないため、内容に自信がないときは先にこのツールを使ってください。"
    ),
    annotations=READ_ONLY,
)
def validate_opportunity(
    payload: WritePayload,
    opportunity_id: Annotated[
        str | None,
        Field(description="更新前提で検証する場合の対象ID。指定するとその1件を重複判定から除外します。"),
    ] = None,
) -> MCPValidationResponse:
    request = _parse_payload(payload, MCPWriteRequest)
    _rate_limit(request.client_name, "validate")
    data = _write_input(request)
    with SessionLocal() as db:
        errors = validate_write(db, data=data)
        if errors:
            raise _domain_error(request, "validate", DomainValidationError(errors))
        duplicates = find_exact_duplicates(
            db,
            company_name=data.company_name,
            event_name=data.event_name,
            exclude_id=opportunity_id,
        )
        return MCPValidationResponse.model_validate(
            {
                "valid": True,
                "message": (
                    "この内容で登録できます。"
                    if not duplicates
                    else "内容は妥当ですが、同じ企業の同名イベントが既に登録されています。"
                ),
                "duplicates": [opportunity_summary(item) for item in duplicates],
            }
        )


@mcp.tool(
    title="募集情報を追加",
    description=(
        "募集情報を1件追加します。request_idはクライアント側で一意にし、再試行時は同じ値を使用してください。"
        "payload内の固定値はget_master_values／get_sectorsのnameを指定します。"
        "同じ企業の同名イベントが既にある場合は登録を拒否し、既存の登録を返します。"
    ),
    annotations=APPEND_ONLY,
)
def add_opportunity(
    payload: WritePayload,
    allow_duplicate: Annotated[
        bool,
        Field(description="同名イベントが既にある場合でも別の登録として追加します。別日程・別コースを分けて登録するときだけtrueにしてください。"),
    ] = False,
) -> MCPWriteResponse:
    request = _parse_payload(payload, MCPWriteRequest)
    _rate_limit(request.client_name, "create")
    data = _write_input(request)
    try:
        with SessionLocal() as db:
            item, replayed = write_opportunity(
                db,
                data=data,
                request_id=request.request_id,
                client_name=request.client_name,
                allow_duplicate=allow_duplicate,
            )
            return MCPWriteResponse.model_validate(
                {
                    "success": True,
                    "idempotent_replay": replayed,
                    "message": "募集情報を登録しました",
                    "opportunity": opportunity_dict(item),
                }
            )
    except DomainValidationError as exc:
        raise _domain_error(request, "create", exc) from exc


@mcp.tool(
    title="募集情報を全項目更新",
    description=(
        "既存の募集情報を全項目置換で更新します。部分更新は行わないため、"
        "get_opportunityで現在値を取得し、変更しない項目もそのまま含めた完全なpayloadを送ってください。"
        "状況や締切だけを直す場合はupdate_recruitment_statusを使ってください。"
    ),
    annotations=REPLACING,
)
def update_opportunity(
    opportunity_id: Annotated[str, Field(description="更新対象のid（UUID）。get_opportunityのidをそのまま渡します。")],
    payload: UpdatePayload,
) -> MCPWriteResponse:
    request = _parse_payload(payload, MCPUpdateRequest)
    _rate_limit(request.client_name, "update")
    data = _write_input(request)
    try:
        with SessionLocal() as db:
            item, replayed = write_opportunity(
                db,
                data=data,
                request_id=request.request_id,
                client_name=request.client_name,
                opportunity_id=opportunity_id,
            )
            return MCPWriteResponse.model_validate(
                {
                    "success": True,
                    "idempotent_replay": replayed,
                    "message": "募集情報を更新しました",
                    "opportunity": opportunity_dict(item),
                }
            )
    except DomainValidationError as exc:
        raise _domain_error(request, "update", exc) from exc
    except LookupError as exc:
        raise _json_error({"error": "not_found", "message": "指定された募集情報が見つかりません"}) from exc


@mcp.tool(
    name="update_recruitment_status",
    title="募集状況だけを更新",
    description=(
        "募集状況と締め切りだけを更新します。他の項目は変更しません。"
        "「締切になった」「募集が始まった」といった保守はこのツールで行い、全項目の再送を避けてください。"
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
def update_recruitment_status_tool(
    opportunity_id: Annotated[str, Field(description="更新対象のid（UUID）。")],
    recruitment_status: Annotated[RecruitmentStatusValue, Field(description="新しい募集状況。", examples=["締切"])],
    request_id: Annotated[str, Field(min_length=8, max_length=100, description="操作ごとに一意なID。再試行時のみ同じ値を使います。")],
    client_name: Annotated[str, Field(min_length=1, max_length=100, description="監査ログに記録される呼び出し元の名前。")] = "mcp-client",
    deadline: Annotated[
        str | None,
        Field(description="新しい締め切り（YYYY-MM-DD）。変更しない場合は省略します。"),
    ] = None,
    clear_deadline: Annotated[bool, Field(description="締め切りを未設定に戻す場合はtrueにします。")] = False,
) -> MCPWriteResponse:
    _rate_limit(client_name, "status_update")
    parsed_deadline: date | None = None
    if deadline is not None:
        try:
            parsed_deadline = date.fromisoformat(deadline)
        except ValueError as exc:
            raise _validation_error(
                client_name,
                request_id,
                [
                    {
                        "field": "締め切り",
                        "received": deadline,
                        "reason": "日付として解釈できません",
                        "expected": "YYYY-MM-DD形式（2000-01-01から実行日の5年後まで）",
                        "example": "2026-08-31",
                        "alternative": "未設定に戻す場合はclear_deadlineをtrueにしてください",
                    }
                ],
            ) from exc
    try:
        with SessionLocal() as db:
            item, replayed = update_recruitment_status(
                db,
                opportunity_id=opportunity_id,
                recruitment_status=recruitment_status,
                request_id=request_id,
                client_name=client_name,
                deadline=parsed_deadline,
                clear_deadline=clear_deadline,
            )
            return MCPWriteResponse.model_validate(
                {
                    "success": True,
                    "idempotent_replay": replayed,
                    "message": "募集状況を更新しました",
                    "opportunity": opportunity_dict(item),
                }
            )
    except DomainValidationError as exc:
        with SessionLocal() as db:
            record_failed_attempt(
                db,
                action="status_update",
                request_id=request_id,
                client_name=client_name,
                source_url=None,
                errors=exc.errors,
            )
        raise _validation_error(client_name, request_id, exc.errors) from exc
    except LookupError as exc:
        raise _json_error({"error": "not_found", "message": "指定された募集情報が見つかりません"}) from exc


@mcp.tool(
    title="直近の書き込み履歴を取得",
    description=(
        "自分を含むクライアントによる直近の登録・更新の記録を返します。"
        "同じ募集を登録し直していないか、どの入力が失敗したかを確認できます。"
    ),
    annotations=READ_ONLY,
)
def list_recent_writes(
    client_name: Annotated[
        str | None,
        Field(description="呼び出し元名で絞り込みます。省略すると全クライアントの履歴を返します。"),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=100, description="取得件数（1〜100）。")] = 20,
) -> MCPWriteHistoryResponse:
    with SessionLocal() as db:
        return MCPWriteHistoryResponse.model_validate(
            {"items": recent_write_logs(db, client_name=client_name, limit=limit)}
        )


async def _list_tools_with_security_schemes() -> list[MCPTool]:
    """Advertise per-tool auth so ChatGPT can discover tools before OAuth login.

    The Python SDK version used by this service predates the convenience
    ``securitySchemes`` argument exposed by the TypeScript Apps SDK.  MCP Tool
    objects allow extension fields, so add the same field to the wire response
    while retaining FastMCP's generated schemas.
    """
    tools = await mcp.list_tools()
    return [
        tool.model_copy(
            update={
                "securitySchemes": (
                    [{"type": "noauth"}]
                    if tool.name in ANONYMOUS_TOOLS
                    else [{"type": "oauth2", "scopes": ["mcp"]}]
                )
            }
        )
        for tool in tools
    ]


# FastMCP 1.28 does not expose securitySchemes as a decorator argument. Replace
# only the low-level list handler so the extension is emitted in tools/list.
mcp._mcp_server.list_tools()(_list_tools_with_security_schemes)


def mcp_http_app():
    return mcp.streamable_http_app()
