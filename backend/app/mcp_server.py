import json
from datetime import date, datetime
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
    DESCRIPTION_GUIDANCE,
    ClientName,
    CollectionCheckPayload,
    CollectionCheckRequest,
    CollectionSourceCreatePayload,
    CollectionSourceCreateRequest,
    CollectionSourceUpdatePayload,
    CollectionSourceUpdateRequest,
    CollectionTargetCreatePayload,
    CollectionTargetCreateRequest,
    CollectionTargetResponse,
    CollectionTargetUpdatePayload,
    CollectionTargetUpdateRequest,
    CompanyIndustryUpdatePayload,
    CompanyIndustryUpdateRequest,
    DegreeValue,
    EventFormatValue,
    EventTypeValue,
    GraduationYearValue,
    IndustryValue,
    JobCategoryValue,
    MastersResponse,
    MCPCollectionCheckListResponse,
    MCPCollectionCheckWriteResponse,
    MCPCollectionQueueResponse,
    MCPCollectionSourceWriteResponse,
    MCPCollectionTargetListResponse,
    MCPCollectionWriteResponse,
    MCPCompanyAliasWriteResponse,
    MCPCompanyIndustryWriteResponse,
    MCPCompanyMaintenanceContextResponse,
    MCPCompanyMergeResponse,
    MCPCompanyResolutionResponse,
    MCPDeletePreviewResponse,
    MCPDeleteResponse,
    MCPDuplicateResponse,
    MCPOpportunityPreviewResponse,
    MCPRestoreResponse,
    MCPSearchResponse,
    MCPSectorsResponse,
    MCPStaleOpportunityListResponse,
    MCPUnmonitoredCompanyListResponse,
    MCPUpdateRequest,
    MCPUpsertResponse,
    MCPValidationResponse,
    MCPWriteHistoryResponse,
    MCPWriteRequest,
    MCPWriteResponse,
    OpportunityInput,
    OpportunityPatchPayload,
    OpportunityResponse,
    RecruitmentStatusValue,
    RequestId,
    SortValue,
    UpdatePayload,
    WritePayload,
    validate_https_url,
    validate_source_host,
)
from app.services.collection_targets import (
    collection_check_dict,
    collection_queue,
    collection_source_dict,
    collection_target_dict,
    create_collection_source,
    create_collection_target,
    get_company_maintenance_context,
    list_collection_checks,
    list_collection_targets,
    list_unmonitored_companies,
    record_collection_check,
    undercovered_collection_targets,
    unmonitored_company_dict,
    update_collection_source,
    update_collection_target,
)
from app.services.collection_targets import (
    get_collection_target as get_collection_target_record,
)
from app.services.companies import (
    CompanyIdentityValidationError,
    add_company_alias,
    company_identity_dict,
    delete_company_alias,
    merge_company,
    replace_company_industries,
    resolve_company_candidates,
)
from app.services.errors import pydantic_errors
from app.services.master_cache import master_payload
from app.services.masters import sectors_for_industry
from app.services.normalization import normalize_company_name
from app.services.opportunities import (
    DomainValidationError,
    InvalidSearchCursor,
    classify_duplicate_candidates,
    delete_opportunity,
    ensure_expected_updated_at,
    find_probable_duplicates,
    find_similar_opportunities,
    find_source_url_duplicates,
    get_opportunity_by_public_ref,
    is_patch_replay,
    list_opportunities_requiring_review,
    opportunity_consistency_warnings,
    opportunity_input_dict,
    opportunity_patch_changes,
    preview_opportunity_deletion,
    probable_duplicate_warning,
    recent_write_logs,
    record_failed_attempt,
    restore_opportunity,
    search_opportunities,
    source_duplicate_warning,
    update_recruitment_status,
    validate_write,
    verify_opportunity,
    write_opportunity,
)
from app.services.opportunities import (
    get_opportunity as get_opportunity_record,
)
from app.services.rate_limit import register_validation_failure
from app.services.serialization import detail_url, master_dict, opportunity_dict, opportunity_summary

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
        "find_opportunities_by_source_url",
    }
)

mcp = FastMCP(
    "All Job",
    instructions=(
        "日本のインターン・本選考情報を検索・登録・更新・削除・復元するMCPです。"
        "検索はsearch_opportunityで概要を取り、全文が必要な1件はget_opportunityで取得します。"
        "追加・更新の前にget_master_valuesとget_sectorsで固定値を確認し、"
        "同じ募集が登録済みでないかfind_similar_opportunitiesで確かめてください。"
        "同名イベントでも対象学年・実施日・対象職種のいずれかが異なれば別募集として登録されます"
        "（例: 同じイベント名を28卒・29卒で使い回す企業）。allow_duplicateは全く同じ日程・コースを"
        "意図的に複数登録する場合だけ使ってください。"
        "情報源URLが既存募集と重ならないかfind_opportunities_by_source_urlでも確認してください。"
        "企業名が略称・英語名・誤記かもしれない場合はresolve_companyで候補を確認し、"
        "同一企業と公式情報で確認できた場合だけadd_company_aliasで別名を登録してから募集を書き込んでください。"
        "企業の業界・業種カテゴリを管理する場合はset_company_industriesでcompany_idとカテゴリ一覧を指定してください。"
        "自信がない入力はvalidate_opportunityで先に検証できます。"
        "締切など状況だけを直す場合はupdate_recruitment_statusを使い、全項目の再送は避けてください。"
        "公式ページを確認して内容が変わっていない場合はverify_opportunityを使って確認だけを記録してください。"
        "日付と募集状況の矛盾、または公式情報の再確認対象はlist_stale_opportunitiesで優先順に確認してください。"
        "定期再確認の対象は募集予定・募集中・通年募集です。締切やその他の終了状態は対象から除外されます。"
        "その他の一部項目だけを直す場合はpreview_opportunity_patchで差分を確認してからpatch_opportunityを使ってください。"
        "誤登録を削除する場合はpreview_delete_opportunityで影響を確認してからdelete_opportunityを使ってください。"
        "誤って削除した募集はrestore_opportunityで同じIDと公開コードのまま復元できます。"
        "日付はYYYY-MM-DD、URLはhttpsを使用し、推測できない任意項目はnullにしてください。"
        f"募集のdescriptionは{DESCRIPTION_GUIDANCE}"
        "自由記述には出典の文章を転記せず、日程・対象・報酬などの事実だけを自分の言葉で書いてください。"
        "出典独自の言い回しやキャッチコピー、担当者名などの個人名、個人宛の連絡先は登録しないでください。"
        "情報源には企業自身の採用ページなど一次情報を指定し、求人サイトや口コミサイトの掲載ページは使用しないでください。"
        "情報収集を進める場合はget_collection_queueで次の企業を取得し、確認後は募集の有無にかかわらず"
        "record_collection_checkで結果を記録してください。収集対象と確認履歴は運営者だけが操作できます。"
        "企業マスタにあるが未監視の企業を棚卸しする場合はlist_unmonitored_companiesを使い、返されたcompany_idを"
        "add_collection_targetへ指定してください。"
        "企業の複数募集をまとめて保守する場合はget_company_maintenance_contextで公式URLと、定期再確認対象の募集の最終確認日時を取得してください。"
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
PATCHING = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
DELETING = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)


def _json_error(payload: dict[str, Any]) -> ToolError:
    return ToolError(json.dumps(payload, ensure_ascii=False, default=str))


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


def _collection_source_url(request: Any) -> str | None:
    source_url = getattr(request, "source_url", None) or getattr(request, "url", None)
    if source_url:
        return source_url
    sources = getattr(request, "sources", None) or []
    return sources[0].url if sources else None


def _parse_collection_payload(raw: dict[str, Any], model: type[Any], action: str) -> Any:
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
                source_url=None,
                errors=errors,
                entity_type="collection_target",
            )
        raise _validation_error(client_name, request_id, errors) from exc


def _parse_company_payload(raw: dict[str, Any], model: type[Any], action: str) -> Any:
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
                source_url=None,
                errors=errors,
                entity_type="company",
            )
        raise _validation_error(client_name, request_id, errors) from exc


def _collection_domain_error(request: Any, action: str, exc: DomainValidationError) -> ToolError:
    with SessionLocal() as db:
        record_failed_attempt(
            db,
            action=action,
            request_id=request.request_id,
            client_name=request.client_name,
            source_url=_collection_source_url(request),
            errors=exc.errors,
            entity_type="collection_target",
        )
    return _validation_error(request.client_name, request.request_id, exc.errors)


def _company_domain_error(
    *, client_name: str, request_id: str | None, action: str, exc: CompanyIdentityValidationError
) -> ToolError:
    with SessionLocal() as db:
        record_failed_attempt(
            db,
            action=action,
            request_id=request_id,
            client_name=client_name,
            source_url=None,
            errors=exc.errors,
            entity_type="company",
        )
    return _validation_error(client_name, request_id, exc.errors)


def _write_input(request: MCPWriteRequest | MCPUpdateRequest) -> OpportunityInput:
    return OpportunityInput.model_validate(request.model_dump(exclude={"request_id", "client_name"}))


def _source_url_warnings(db: Any, *, data: OpportunityInput, opportunity_id: str) -> list[dict[str, Any]]:
    """Non-blocking source_url collision warnings for a just-completed create.

    Already used on the validate/patch-preview paths via find_source_url_duplicates /
    source_duplicate_warning; surfaced here too so add_opportunity/upsert_opportunity don't require a
    separate find_opportunities_by_source_url round trip just to learn about it.
    """
    matches = find_source_url_duplicates(db, source_url=data.source_url, exclude_id=opportunity_id)
    return [source_duplicate_warning(matches, data.source_url)] if matches else []


def _consistency_warnings(data: OpportunityInput) -> list[dict[str, Any]]:
    return opportunity_consistency_warnings(
        recruitment_status=data.recruitment_status,
        deadline=data.deadline,
        event_start_date=data.event_start_date,
        event_end_date=data.event_end_date,
    )


def _probable_duplicate_warnings(db: Any, *, data: OpportunityInput, opportunity_id: str) -> list[dict[str, Any]]:
    matches = find_probable_duplicates(db, data=data, exclude_id=opportunity_id)
    return [probable_duplicate_warning(matches)] if matches else []


def _write_warnings(db: Any, *, data: OpportunityInput, opportunity_id: str) -> list[dict[str, Any]]:
    return (
        _consistency_warnings(data)
        + _source_url_warnings(db, data=data, opportunity_id=opportunity_id)
        + _probable_duplicate_warnings(db, data=data, opportunity_id=opportunity_id)
    )


def _prepare_opportunity_patch(
    db: Any,
    *,
    opportunity_id: str,
    changes: dict[str, Any],
    expected_updated_at: datetime,
    request_id: str,
    client_name: str,
    allow_idempotent_replay: bool = False,
) -> tuple[Any, OpportunityInput]:
    item = get_opportunity_record(db, opportunity_id)
    if item is None:
        raise _json_error({"error": "not_found", "message": "指定された募集情報が見つかりません"})
    if not changes:
        errors = [{"field": "変更内容", "received": {}, "reason": "変更する項目を1件以上指定してください"}]
        raise _validation_error(client_name, request_id, errors)
    try:
        if not allow_idempotent_replay:
            ensure_expected_updated_at(item, expected_updated_at)
        data = OpportunityInput.model_validate(opportunity_input_dict(item) | changes)
    except DomainValidationError as exc:
        raise _validation_error(client_name, request_id, exc.errors) from exc
    except ValidationError as exc:
        merged = opportunity_input_dict(item) | changes
        errors = pydantic_errors(exc, merged)
        record_failed_attempt(
            db,
            action="patch",
            request_id=request_id,
            client_name=client_name,
            source_url=merged.get("source_url"),
            errors=errors,
        )
        raise _validation_error(client_name, request_id, errors) from exc
    errors = validate_write(db, data=data)
    if errors:
        raise _validation_error(client_name, request_id, errors)
    if not allow_idempotent_replay and not opportunity_patch_changes(item, data):
        errors = [{"field": "変更内容", "received": changes, "reason": "現在値から変わる項目がありません"}]
        raise _validation_error(client_name, request_id, errors)
    return item, data


@mcp.tool(
    title="募集情報を検索",
    description=(
        "登録済みの募集情報をキーワードと固定値で検索し、概要の一覧を返します。ログインは不要です。"
        "続きがある場合はnext_cursorを同じ検索条件でcursorへ渡すため、一覧の途中でレコードが削除されても"
        "ページ境界の重複や取得漏れが起きません。説明文は冒頭のみ返るため、全文が必要な1件は"
        "get_opportunityで取得してください。"
    ),
    annotations=READ_ONLY,
)
def search_opportunity(
    query: Annotated[
        str | None,
        Field(description="企業名・イベント名・職種・内容・募集要件に対するキーワード。表記揺れや軽微なタイプミスも検索できます。"),
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
        Field(
            description=(
                "並び順。relevance=関連度順、deadline=締切が近い順（締切なしは末尾）、"
                "updated=更新が新しい順、created=登録が新しい順。キーワードなしのrelevanceは締切順になります。"
            )
        ),
    ] = "relevance",
    cursor: Annotated[
        str | None,
        Field(
            max_length=2048,
            description=(
                "続きの取得に使うカーソル。初回はnullにし、続きがある間は直前の応答のnext_cursorを"
                "検索条件を変えずにそのまま渡します。"
            ),
        ),
    ] = None,
    per_page: Annotated[int, Field(ge=1, le=50, description="1ページあたりの件数（1〜50）。")] = 20,
) -> MCPSearchResponse:
    with SessionLocal() as db:
        try:
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
                page=None,
                per_page=per_page,
                cursor=cursor,
            )
        except InvalidSearchCursor as exc:
            raise _json_error({"error": "invalid_cursor", "message": str(exc)}) from exc
        return MCPSearchResponse.model_validate(
            {
                "items": [opportunity_summary(item) for item in result.items],
                "total": result.total,
                "per_page": result.per_page,
                "next_cursor": result.next_cursor,
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
    name="resolve_company",
    title="企業名から既存企業候補を解決",
    description=(
        "正式名・登録済み別名の完全一致を優先し、見つからない場合は部分一致とタイプミスを含む候補を返します。"
        "partial／fuzzyは候補でしかなく、自動的に同一企業とは扱いません。公式サイト等で同一企業と確認した場合だけ"
        "add_company_aliasを呼んでください。収集対象企業も検索対象に含むため認証が必要です。"
    ),
    annotations=READ_ONLY,
)
def resolve_company_tool(
    company_name: Annotated[
        str,
        Field(min_length=1, max_length=200, description="正式名、略称、英語名、または誤記の可能性がある企業名。"),
    ],
    limit: Annotated[int, Field(ge=1, le=10, description="返す候補数（1〜10）。")] = 5,
) -> MCPCompanyResolutionResponse:
    with SessionLocal() as db:
        try:
            candidates = resolve_company_candidates(db, company_name, limit=limit)
        except CompanyIdentityValidationError as exc:
            raise _company_domain_error(
                client_name="mcp-client", request_id=None, action="company_resolve", exc=exc
            ) from exc
        match_type = candidates[0].match_type if candidates else "none"
        exact = match_type in {"canonical_exact", "alias_exact"}
        return MCPCompanyResolutionResponse.model_validate(
            {
                "query": company_name,
                "normalized_query": normalize_company_name(company_name),
                "match_type": match_type,
                "requires_confirmation": not exact,
                "message": (
                    "登録済みの企業と完全一致しました。"
                    if exact
                    else (
                        "類似する企業候補があります。同一企業か公式情報で確認してください。"
                        if candidates
                        else "既存企業の候補は見つかりませんでした。正式名称で新規登録してください。"
                    )
                ),
                "candidates": [
                    {
                        "company": company_identity_dict(candidate.company),
                        "match_type": candidate.match_type,
                        "matched_name": candidate.matched_name,
                        "score": candidate.score,
                    }
                    for candidate in candidates
                ],
            }
        )


@mcp.tool(
    name="add_company_alias",
    title="確認済みの企業別名を追加",
    description=(
        "resolve_companyが返した候補を公式情報で同一企業と確認した後、その企業へ略称・英語名・旧社名などを追加します。"
        "曖昧一致だけを根拠に登録してはいけません。追加後は募集登録・重複判定・検索の全経路で別名が使われます。"
        "認証が必要です。"
    ),
    annotations=APPEND_ONLY,
)
def add_company_alias_tool(
    company_id: Annotated[int, Field(ge=1, description="resolve_companyが返した企業ID。")],
    alias: Annotated[str, Field(min_length=1, max_length=200, description="確認済みの略称・英語名・旧社名。")],
    request_id: Annotated[RequestId, Field(description="操作ごとに一意なID。再試行時は同じ値を使用します。")],
    client_name: ClientName = "mcp-client",
) -> MCPCompanyAliasWriteResponse:
    try:
        with SessionLocal() as db:
            company, changed, replayed = add_company_alias(
                db,
                company_id=company_id,
                alias=alias,
                request_id=request_id,
                client_name=client_name,
            )
            return MCPCompanyAliasWriteResponse.model_validate(
                {
                    "success": True,
                    "idempotent_replay": replayed,
                    "changed": changed,
                    "message": (
                        "同じ別名追加操作は処理済みです"
                        if replayed
                        else ("企業別名を追加しました" if changed else "同じ企業名または別名が既に登録済みです")
                    ),
                    "company": company_identity_dict(company),
                }
            )
    except CompanyIdentityValidationError as exc:
        raise _company_domain_error(
            client_name=client_name, request_id=request_id, action="company_alias_add", exc=exc
        ) from exc
    except LookupError as exc:
        raise _json_error({"error": "not_found", "message": "指定された企業が見つかりません"}) from exc


@mcp.tool(
    name="set_company_industries",
    title="企業のカテゴリを一括設定",
    description=(
        "既存企業に紐づく業界・業種カテゴリを、指定した一覧で全置換します。"
        "小売・流通とIT・通信のように複数業界を登録でき、一覧の先頭が代表カテゴリになります。"
        "収集対象が未作成の企業にも設定できます。resolve_companyまたはlist_unmonitored_companiesで企業IDを確認し、"
        "業界ごとに1件、必要な場合はその業界に属する業種を指定してください。"
        "既存カテゴリを残して追加する場合は、現在のカテゴリも一覧に含めてください。認証が必要です。"
    ),
    annotations=REPLACING,
)
def set_company_industries_tool(payload: CompanyIndustryUpdatePayload) -> MCPCompanyIndustryWriteResponse:
    request = _parse_company_payload(payload, CompanyIndustryUpdateRequest, "company_industries_update")
    try:
        with SessionLocal() as db:
            company, replayed = replace_company_industries(
                db,
                company_id=request.company_id,
                entries=request.industries,
                request_id=request.request_id,
                client_name=request.client_name,
            )
            return MCPCompanyIndustryWriteResponse.model_validate(
                {
                    "success": True,
                    "idempotent_replay": replayed,
                    "message": "同じ企業カテゴリ設定は処理済みです" if replayed else "企業カテゴリを設定しました",
                    "company": company_identity_dict(company),
                }
            )
    except CompanyIdentityValidationError as exc:
        raise _company_domain_error(
            client_name=request.client_name,
            request_id=request.request_id,
            action="company_industries_update",
            exc=exc,
        ) from exc
    except LookupError as exc:
        raise _json_error({"error": "not_found", "message": "指定された企業が見つかりません"}) from exc


@mcp.tool(
    name="delete_company_alias",
    title="誤った企業別名を削除",
    description=(
        "resolve_companyが返すaliases内のIDを指定し、誤登録された別名を削除します。"
        "削除後、その表記は企業の自動解決・重複判定・検索に使われなくなります。認証が必要です。"
    ),
    annotations=DELETING,
)
def delete_company_alias_tool(
    alias_id: Annotated[int, Field(ge=1, description="削除する企業別名ID。")],
    request_id: Annotated[RequestId, Field(description="操作ごとに一意なID。再試行時は同じ値を使用します。")],
    client_name: ClientName = "mcp-client",
) -> MCPCompanyAliasWriteResponse:
    try:
        with SessionLocal() as db:
            company, replayed = delete_company_alias(
                db,
                alias_id=alias_id,
                request_id=request_id,
                client_name=client_name,
            )
            return MCPCompanyAliasWriteResponse.model_validate(
                {
                    "success": True,
                    "idempotent_replay": replayed,
                    "changed": not replayed,
                    "message": "同じ別名削除操作は処理済みです" if replayed else "企業別名を削除しました",
                    "company": company_identity_dict(company),
                }
            )
    except CompanyIdentityValidationError as exc:
        raise _company_domain_error(
            client_name=client_name, request_id=request_id, action="company_alias_delete", exc=exc
        ) from exc
    except LookupError as exc:
        raise _json_error({"error": "not_found", "message": "指定された企業別名が見つかりません"}) from exc


@mcp.tool(
    name="merge_company",
    title="確認済みの重複企業を統合",
    description=(
        "公式情報で同一法人・同一の採用主体と確認済みの重複企業を、統合元IDから統合先IDへ物理統合します。"
        "募集、旧正式名を含む別名、業界分類、収集対象・情報源・確認履歴、企業操作の冪等性記録を一つの"
        "トランザクションで移し、統合元のCompanyを削除します。IDの取り違えは戻せないため、"
        "必ずresolve_companyの結果と公式情報を確認してから実行してください。認証が必要です。"
    ),
    annotations=DELETING,
)
def merge_company_tool(
    source_company_id: Annotated[int, Field(ge=1, description="削除して統合先へ移す重複CompanyのID。")],
    target_company_id: Annotated[int, Field(ge=1, description="残す正規CompanyのID。")],
    request_id: Annotated[RequestId, Field(description="操作ごとに一意なID。再試行時は同じ値を使用します。")],
    client_name: ClientName = "mcp-client",
) -> MCPCompanyMergeResponse:
    try:
        with SessionLocal() as db:
            target, migration, replayed = merge_company(
                db,
                source_company_id=source_company_id,
                target_company_id=target_company_id,
                request_id=request_id,
                client_name=client_name,
            )
            return MCPCompanyMergeResponse.model_validate(
                {
                    "success": True,
                    "idempotent_replay": replayed,
                    "message": "同じ企業統合操作は処理済みです" if replayed else "企業を統合し、統合元を削除しました",
                    "source_company_id": source_company_id,
                    "target_company": company_identity_dict(target),
                    "migration": migration,
                }
            )
    except CompanyIdentityValidationError as exc:
        raise _company_domain_error(
            client_name=client_name, request_id=request_id, action="company_merge", exc=exc
        ) from exc
    except LookupError as exc:
        raise _json_error({"error": "not_found", "message": "指定された統合元または統合先の企業が見つかりません"}) from exc


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
    name="find_opportunities_by_source_url",
    title="同じ一次情報URLの募集を探す",
    description=(
        "計測パラメータ、フラグメント、末尾スラッシュなどを正規化し、同じ企業公式ページを使う募集を返します。"
        "同じページに複数募集がある場合もあるため、一致は警告であり一律の登録禁止ではありません。"
    ),
    annotations=READ_ONLY,
)
def find_opportunities_by_source_url_tool(
    source_url: Annotated[str, Field(description="確認する企業公式の一次情報URL（https必須）。")],
) -> MCPDuplicateResponse:
    try:
        validated = validate_source_host(validate_https_url(source_url) or source_url)
    except ValueError as exc:
        raise _json_error(
            {
                "error": "validation_failed",
                "message": "企業公式のhttps URLを指定してください",
                "errors": [{"field": "情報源", "received": source_url, "reason": str(exc)}],
            }
        ) from exc
    with SessionLocal() as db:
        matches = find_source_url_duplicates(db, source_url=validated)
        return MCPDuplicateResponse.model_validate(
            {
                "message": (
                    "同じ一次情報URLの募集は見つかりませんでした。"
                    if not matches
                    else "同じ一次情報URLの募集があります。別の募集であることを確認してください。"
                ),
                "matches": [opportunity_summary(item) for item in matches],
            }
        )


@mcp.tool(
    title="登録内容を検証（書き込みなし）",
    description=(
        "payloadを保存せずに検証し、固定値の誤りと重複の疑いを返します。"
        "検証に失敗しても登録は行われないため、内容に自信がないときは先にこのツールを使ってください。"
        f"{DESCRIPTION_GUIDANCE}"
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
    data = _write_input(request)
    with SessionLocal() as db:
        errors = validate_write(db, data=data)
        if errors:
            raise _domain_error(request, "validate", DomainValidationError(errors))
        duplicates, probable_duplicates = classify_duplicate_candidates(
            db,
            company_name=data.company_name,
            event_name=data.event_name,
            graduation_years=data.graduation_years,
            event_start_date=data.event_start_date,
            job_categories=data.job_categories,
            exclude_id=opportunity_id,
        )
        source_matches = find_source_url_duplicates(db, source_url=data.source_url, exclude_id=opportunity_id)
        seen = {item.id for item in duplicates}
        duplicates.extend(item for item in source_matches if item.id not in seen)
        warnings = _consistency_warnings(data)
        if probable_duplicates:
            warnings.append(probable_duplicate_warning(probable_duplicates))
        return MCPValidationResponse.model_validate(
            {
                "valid": True,
                "message": (
                    "この内容で登録できます。"
                    if not duplicates and not warnings
                    else "内容は保存できますが、重複または日付・募集状況の確認が必要です。"
                ),
                "duplicates": [opportunity_summary(item) for item in duplicates],
                "warnings": warnings,
            }
        )


@mcp.tool(
    title="募集情報を追加",
    description=(
        "募集情報を1件追加します。request_idはクライアント側で一意にし、再試行時は同じ値を使用してください。"
        "payload内の固定値はget_master_values／get_sectorsのnameを指定します。"
        "同じ企業・同名イベントで、対象学年・実施日・対象職種も一致する場合だけ登録を拒否し、既存の登録を返します。"
        "同名イベントでも対象学年・実施日・対象職種のいずれかが異なれば「同名だが別募集」として登録し、"
        "warningsで既存の登録を知らせます（会社が28卒・29卒で同じイベント名を使い回す場合など）。"
        f"{DESCRIPTION_GUIDANCE}"
        "自由記述は出典の文章を転記せず事実だけを要約し、個人名・個人宛の連絡先は含めないでください。"
    ),
    annotations=APPEND_ONLY,
)
def add_opportunity(
    payload: WritePayload,
    allow_duplicate: Annotated[
        bool,
        Field(
            description=(
                "対象学年・実施日・対象職種まで一致する完全な重複でも、別の登録として追加します。"
                "同一の日程・コースを意図的に複数登録するときだけtrueにしてください。"
                "対象学年・実施日・対象職種のいずれかが違う場合はfalseのままで登録できます。"
            )
        ),
    ] = False,
    collection_target_id: Annotated[
        int | None,
        Field(
            ge=1,
            description=(
                "get_collection_queueで取得した収集対象ID。指定すると募集登録と確認履歴を同時に記録します。"
                "省略しても、企業名・業界が一致する有効な収集対象があれば自動で紐付けて確認履歴を記録します。"
            ),
        ),
    ] = None,
) -> MCPWriteResponse:
    request = _parse_payload(payload, MCPWriteRequest)
    data = _write_input(request)
    try:
        with SessionLocal() as db:
            item, replayed = write_opportunity(
                db,
                data=data,
                request_id=request.request_id,
                client_name=request.client_name,
                allow_duplicate=allow_duplicate,
                collection_target_id=collection_target_id,
            )
            return MCPWriteResponse.model_validate(
                {
                    "success": True,
                    "idempotent_replay": replayed,
                    "message": "募集情報を登録しました",
                    "opportunity": opportunity_dict(item),
                    "warnings": _write_warnings(db, data=data, opportunity_id=item.id),
                }
            )
    except DomainValidationError as exc:
        raise _domain_error(request, "create", exc) from exc


@mcp.tool(
    name="upsert_opportunity",
    title="募集情報を検索なしで登録（重複時は既存を返す）",
    description=(
        "同じ企業・同名イベントで、対象学年・実施日・対象職種も一致する場合はエラーにせず既存の登録をそのまま返し、"
        "そうでなければ新規登録します。同名イベントでも対象学年・実施日・対象職種のいずれかが異なれば別募集として"
        "新規登録し、warningsで既存の登録を知らせます（会社が28卒・29卒で同じイベント名を使い回す場合など）。"
        "find_similar_opportunitiesとadd_opportunityを毎回2回呼ぶ手間を1回にまとめたツールです。"
        "対象学年・実施日・対象職種まで一致する完全な重複を意図的に複数登録したい場合は、"
        "代わりにadd_opportunityをallow_duplicate=trueで使ってください。"
        f"{DESCRIPTION_GUIDANCE}"
    ),
    annotations=APPEND_ONLY,
)
def upsert_opportunity(
    payload: WritePayload,
    collection_target_id: Annotated[
        int | None,
        Field(
            ge=1,
            description=(
                "get_collection_queueで取得した収集対象ID。指定すると新規登録時に募集登録と確認履歴を同時に記録します。"
                "省略しても、企業名・業界が一致する有効な収集対象があれば自動で紐付けます。"
            ),
        ),
    ] = None,
) -> MCPUpsertResponse:
    request = _parse_payload(payload, MCPWriteRequest)
    data = _write_input(request)
    try:
        with SessionLocal() as db:
            item, replayed = write_opportunity(
                db,
                data=data,
                request_id=request.request_id,
                client_name=request.client_name,
                allow_duplicate=False,
                collection_target_id=collection_target_id,
            )
            return MCPUpsertResponse.model_validate(
                {
                    "result": "created",
                    "message": "募集情報を登録しました",
                    "opportunity": opportunity_dict(item),
                    "warnings": _write_warnings(db, data=data, opportunity_id=item.id),
                }
            )
    except DomainValidationError as exc:
        # _duplicate_error() is the only error builder on this path that sets "existing" - an
        # unambiguous discriminator between "same posting already registered" (return it) and any
        # other validation failure (bad master value, etc., which still propagates as usual).
        duplicate = next((error for error in exc.errors if error.get("existing")), None)
        if duplicate is None:
            raise _domain_error(request, "create", exc) from exc
        with SessionLocal() as db:
            existing_item = get_opportunity_record(db, duplicate["existing"][0]["id"])
            if existing_item is None:
                raise _domain_error(request, "create", exc) from exc
            return MCPUpsertResponse.model_validate(
                {
                    "result": "existing",
                    "message": "同じ企業の同名イベントが既に登録されているため、既存の登録を返しました",
                    "opportunity": opportunity_dict(existing_item),
                }
            )


@mcp.tool(
    title="募集情報を全項目更新",
    description=(
        "既存の募集情報を全項目置換で更新します。部分更新は行わないため、"
        "get_opportunityで現在値を取得し、変更しない項目もそのまま含めた完全なpayloadを送ってください。"
        "状況や締切だけを直す場合はupdate_recruitment_statusを使ってください。"
        f"descriptionを変更する場合は、{DESCRIPTION_GUIDANCE}"
        "自由記述は出典の文章を転記せず事実だけを要約し、個人名・個人宛の連絡先は含めないでください。"
        "このツールはDBの内容を書き換えるだけで、公式情報確認日時（source_checked_at）は変更しません。"
        "更新にあたって一次情報を確認した場合は、verify_opportunityまたはrecord_collection_checkで別途記録してください。"
        "expected_updated_atが現在値と違う場合は上書きせず拒否します。取得後に別の変更が入っていないか、"
        "必ずget_opportunityで直前に取得したupdated_atを渡してください。"
    ),
    annotations=REPLACING,
)
def update_opportunity(
    opportunity_id: Annotated[str, Field(description="更新対象のid（UUID）。get_opportunityのidをそのまま渡します。")],
    payload: UpdatePayload,
    expected_updated_at: Annotated[
        datetime,
        Field(description="get_opportunityで取得した現在のupdated_at。取得後の競合更新を検出します。"),
    ],
) -> MCPWriteResponse:
    request = _parse_payload(payload, MCPUpdateRequest)
    data = _write_input(request)
    try:
        with SessionLocal() as db:
            item, replayed = write_opportunity(
                db,
                data=data,
                request_id=request.request_id,
                client_name=request.client_name,
                opportunity_id=opportunity_id,
                expected_updated_at=expected_updated_at,
            )
            return MCPWriteResponse.model_validate(
                {
                    "success": True,
                    "idempotent_replay": replayed,
                    "message": "募集情報を更新しました",
                    "opportunity": opportunity_dict(item),
                    "warnings": _write_warnings(db, data=data, opportunity_id=item.id),
                }
            )
    except DomainValidationError as exc:
        raise _domain_error(request, "update", exc) from exc
    except LookupError as exc:
        raise _json_error({"error": "not_found", "message": "指定された募集情報が見つかりません"}) from exc


@mcp.tool(
    name="preview_opportunity_patch",
    title="募集情報の部分更新をプレビュー",
    description=(
        "保存せずに現在値へ変更項目をマージし、全項目検証、更新競合、変更差分、一次情報URLの重複を確認します。"
        "日付と募集状況の矛盾もwarningsとして返します。"
        "get_opportunityのupdated_atをexpected_updated_atへそのまま指定してください。認証が必要です。"
    ),
    annotations=READ_ONLY,
)
def preview_opportunity_patch_tool(
    opportunity_id: Annotated[str, Field(description="更新対象のUUID。")],
    changes: OpportunityPatchPayload,
    expected_updated_at: Annotated[
        datetime,
        Field(description="get_opportunityで取得した現在のupdated_at。取得後の競合更新を検出します。"),
    ],
    request_id: Annotated[str, Field(min_length=8, max_length=100, description="検証操作を識別する一意なID。")],
    client_name: Annotated[str, Field(min_length=1, max_length=100)] = "mcp-client",
) -> MCPOpportunityPreviewResponse:
    with SessionLocal() as db:
        item, data = _prepare_opportunity_patch(
            db,
            opportunity_id=opportunity_id,
            changes=changes,
            expected_updated_at=expected_updated_at,
            request_id=request_id,
            client_name=client_name,
        )
        matches = find_source_url_duplicates(db, source_url=data.source_url, exclude_id=item.id)
        warnings = _consistency_warnings(data)
        if matches:
            warnings.append(source_duplicate_warning(matches, data.source_url))
        warnings += _probable_duplicate_warnings(db, data=data, opportunity_id=item.id)
        diff = opportunity_patch_changes(item, data)
        return MCPOpportunityPreviewResponse.model_validate(
            {
                "valid": True,
                "message": "変更内容を保存できます。" if not warnings else "保存できますが、確認が必要な警告があります。",
                "expected_updated_at": item.updated_at,
                "changes": diff,
                "warnings": warnings,
                "merged_payload": data.model_dump(mode="json"),
            }
        )


@mcp.tool(
    name="patch_opportunity",
    title="募集情報を部分更新",
    description=(
        "指定した項目だけを更新し、サーバー側で現在値とマージして全項目を再検証します。"
        "expected_updated_atが現在値と違う場合は上書きせず拒否します。先にpreview_opportunity_patchを実行してください。"
        f"descriptionを変更する場合は、{DESCRIPTION_GUIDANCE}"
        "このツールはDBの内容を書き換えるだけで、公式情報確認日時（source_checked_at）は変更しません。"
        "タグや分類だけの修正のように、一次情報を読み直していない修正でも安全に使えます。"
        "一次情報を確認した場合は、verify_opportunityまたはrecord_collection_checkで別途記録してください。"
    ),
    annotations=PATCHING,
)
def patch_opportunity_tool(
    opportunity_id: Annotated[str, Field(description="更新対象のUUID。")],
    changes: OpportunityPatchPayload,
    expected_updated_at: Annotated[
        datetime,
        Field(description="get_opportunityまたはプレビューで取得したupdated_at。"),
    ],
    request_id: Annotated[str, Field(min_length=8, max_length=100, description="操作ごとに一意なID。")],
    client_name: Annotated[str, Field(min_length=1, max_length=100)] = "mcp-client",
) -> MCPWriteResponse:
    try:
        with SessionLocal() as db:
            _, data = _prepare_opportunity_patch(
                db,
                opportunity_id=opportunity_id,
                changes=changes,
                expected_updated_at=expected_updated_at,
                request_id=request_id,
                client_name=client_name,
                allow_idempotent_replay=is_patch_replay(
                    db, request_id=request_id, opportunity_id=opportunity_id
                ),
            )
            item, replayed = write_opportunity(
                db,
                data=data,
                request_id=request_id,
                client_name=client_name,
                opportunity_id=opportunity_id,
                expected_updated_at=expected_updated_at,
                action="patch",
            )
            return MCPWriteResponse.model_validate(
                {
                    "success": True,
                    "idempotent_replay": replayed,
                    "message": "募集情報を部分更新しました",
                    "opportunity": opportunity_dict(item),
                    "warnings": _write_warnings(db, data=data, opportunity_id=item.id),
                }
            )
    except DomainValidationError as exc:
        request = type(
            "PatchRequest",
            (),
            {"request_id": request_id, "client_name": client_name, "source_url": changes.get("source_url")},
        )()
        raise _domain_error(request, "patch", exc) from exc
    except LookupError as exc:
        raise _json_error({"error": "not_found", "message": "指定された募集情報が見つかりません"}) from exc


@mcp.tool(
    name="update_recruitment_status",
    title="募集状況だけを更新",
    description=(
        "募集状況と締め切りだけを更新します。他の項目は変更しません。"
        "「締切になった」「募集が始まった」といった保守はこのツールで行い、全項目の再送を避けてください。"
        "get_opportunityで取得したupdated_atを必ず渡し、取得後に別の更新があれば拒否します。"
        "日付と募集状況が矛盾する場合も保存はしますが、warningsで公式情報の再確認を促します。"
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
def update_recruitment_status_tool(
    opportunity_id: Annotated[str, Field(description="更新対象のid（UUID）。")],
    recruitment_status: Annotated[RecruitmentStatusValue, Field(description="新しい募集状況。", examples=["締切"])],
    expected_updated_at: Annotated[
        datetime,
        Field(description="get_opportunityで取得した現在のupdated_at。取得後に更新されていた場合は拒否します。"),
    ],
    request_id: Annotated[str, Field(min_length=8, max_length=100, description="操作ごとに一意なID。再試行時のみ同じ値を使います。")],
    client_name: Annotated[str, Field(min_length=1, max_length=100, description="監査ログに記録される呼び出し元の名前。")] = "mcp-client",
    deadline: Annotated[
        str | None,
        Field(description="新しい締め切り（YYYY-MM-DD）。変更しない場合は省略します。"),
    ] = None,
    clear_deadline: Annotated[bool, Field(description="締め切りを未設定に戻す場合はtrueにします。")] = False,
) -> MCPWriteResponse:
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
                expected_updated_at=expected_updated_at,
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
                    "warnings": opportunity_consistency_warnings(
                        recruitment_status=item.status.name,
                        deadline=item.deadline,
                        event_start_date=item.event_start_date,
                        event_end_date=item.event_end_date,
                    ),
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
    name="verify_opportunity",
    title="募集情報の確認のみを記録",
    description=(
        "登録済みの一次情報URLを確認し、募集内容に変更がなかったことを記録します。"
        "source_checked_atだけを更新し、募集内容とupdated_atは変更しません。"
        "募集状況や締め切りが変わった場合はupdate_recruitment_status、他の内容が変わった場合はpatch_opportunityを使ってください。"
    ),
    annotations=APPEND_ONLY,
)
def verify_opportunity_tool(
    opportunity_id: Annotated[str, Field(description="確認した募集情報のid（UUID）。")],
    checked_at: Annotated[
        datetime,
        Field(description="公式ページを確認した日時（タイムゾーン付きISO 8601）。未来の日時は指定できません。"),
    ],
    source_url: Annotated[str, Field(description="確認した登録済みの一次情報URL（https）。")],
    request_id: Annotated[str, Field(min_length=8, max_length=100, description="操作ごとに一意なID。再試行時のみ同じ値を使います。")],
    client_name: Annotated[str, Field(min_length=1, max_length=100, description="監査ログに記録される呼び出し元の名前。")] = "mcp-client",
) -> MCPWriteResponse:
    try:
        source_url = validate_source_host(validate_https_url(source_url) or source_url)
    except ValueError as exc:
        errors = [
            {
                "field": "情報源",
                "received": source_url,
                "reason": str(exc),
                "expected": "企業自身の一次情報であるhttps URL",
                "alternative": "登録済みのsource_urlをget_opportunityで確認してください",
            }
        ]
        with SessionLocal() as db:
            record_failed_attempt(
                db,
                action="verify",
                request_id=request_id,
                client_name=client_name,
                source_url=source_url,
                errors=errors,
            )
        raise _validation_error(client_name, request_id, errors) from exc
    try:
        with SessionLocal() as db:
            item, replayed = verify_opportunity(
                db,
                opportunity_id=opportunity_id,
                checked_at=checked_at,
                source_url=source_url,
                request_id=request_id,
                client_name=client_name,
            )
            return MCPWriteResponse.model_validate(
                {
                    "success": True,
                    "idempotent_replay": replayed,
                    "message": "公式情報の確認のみを記録しました",
                    "opportunity": opportunity_dict(item),
                }
            )
    except DomainValidationError as exc:
        with SessionLocal() as db:
            record_failed_attempt(
                db,
                action="verify",
                request_id=request_id,
                client_name=client_name,
                source_url=source_url,
                errors=exc.errors,
            )
        raise _validation_error(client_name, request_id, exc.errors) from exc
    except LookupError as exc:
        raise _json_error({"error": "not_found", "message": "指定された募集情報が見つかりません"}) from exc


@mcp.tool(
    name="preview_delete_opportunity",
    title="募集情報の削除をプレビュー",
    description=(
        "募集情報を削除した場合の対象と影響を、保存せずに確認します。"
        "返されたexpected_updated_atをdelete_opportunityへそのまま渡してください。認証が必要です。"
    ),
    annotations=READ_ONLY,
)
def preview_delete_opportunity_tool(
    opportunity_id: Annotated[
        str,
        Field(description="削除を検討している募集情報のUUID。get_opportunityのidを指定します。"),
    ],
) -> MCPDeletePreviewResponse:
    with SessionLocal() as db:
        try:
            item, linked_checks = preview_opportunity_deletion(db, opportunity_id=opportunity_id)
        except LookupError as exc:
            raise _json_error({"error": "not_found", "message": "指定された公開中の募集情報が見つかりません"}) from exc
        return MCPDeletePreviewResponse.model_validate(
            {
                "valid": True,
                "message": "この募集情報を削除できます。対象と影響を確認してください。",
                "opportunity": {
                    "id": item.id,
                    "public_code": item.public_code,
                    "company_name": item.company.name,
                    "event_name": item.event_name,
                    "source_url": item.source_url,
                },
                "expected_updated_at": item.updated_at,
                "linked_collection_checks": linked_checks,
                "effects": [
                    "公開検索、詳細ページ、収集対象の登録済み募集一覧に表示されなくなります",
                    "募集情報と収集確認履歴の関連付けは保持されます",
                    "restore_opportunityで同じIDと公開コードのまま復元できます",
                ],
            }
        )


@mcp.tool(
    name="delete_opportunity",
    title="募集情報を削除",
    description=(
        "誤登録や不要になった募集情報を公開データから論理削除します。"
        "先にpreview_delete_opportunityを実行し、そのidとexpected_updated_atを指定してください。"
        "取得後に更新されていた場合は削除せず拒否します。削除後はrestore_opportunityで復元できます。認証が必要です。"
    ),
    annotations=DELETING,
)
def delete_opportunity_tool(
    opportunity_id: Annotated[
        str,
        Field(description="削除対象のUUID。誤削除を避けるため、get_opportunityで取得したidを指定します。"),
    ],
    expected_updated_at: Annotated[
        datetime,
        Field(description="get_opportunityで取得した現在のupdated_at。取得後の競合更新を検出します。"),
    ],
    request_id: Annotated[
        str,
        Field(min_length=8, max_length=100, description="操作ごとに一意なID。再試行時のみ同じ値を使います。"),
    ],
    client_name: Annotated[
        str,
        Field(min_length=1, max_length=100, description="監査ログに記録される呼び出し元の名前。"),
    ] = "mcp-client",
) -> MCPDeleteResponse:
    try:
        with SessionLocal() as db:
            deleted, replayed = delete_opportunity(
                db,
                opportunity_id=opportunity_id,
                expected_updated_at=expected_updated_at,
                request_id=request_id,
                client_name=client_name,
            )
            return MCPDeleteResponse.model_validate(
                {
                    "success": True,
                    "idempotent_replay": replayed,
                    "message": "同じ削除操作は処理済みです" if replayed else "募集情報を論理削除しました",
                    "deleted": deleted,
                }
            )
    except DomainValidationError as exc:
        with SessionLocal() as db:
            record_failed_attempt(
                db,
                action="delete",
                request_id=request_id,
                client_name=client_name,
                source_url=None,
                errors=exc.errors,
            )
        raise _validation_error(client_name, request_id, exc.errors) from exc
    except LookupError as exc:
        raise _json_error({"error": "not_found", "message": "指定された募集情報が見つかりません"}) from exc


@mcp.tool(
    name="restore_opportunity",
    title="削除済み募集情報を復元",
    description=(
        "論理削除された募集情報を、元のIDと公開コードを維持したまま公開状態へ戻します。"
        "同じ企業・同名イベントで対象学年・実施日・対象職種も一致する募集が公開中の場合は、"
        "重複を避けるため復元を拒否します。認証が必要です。"
    ),
    annotations=PATCHING,
)
def restore_opportunity_tool(
    opportunity_id: Annotated[
        str,
        Field(description="delete_opportunityが返した削除済み募集情報のUUID。"),
    ],
    request_id: Annotated[
        str,
        Field(min_length=8, max_length=100, description="操作ごとに一意なID。再試行時のみ同じ値を使います。"),
    ],
    client_name: Annotated[
        str,
        Field(min_length=1, max_length=100, description="監査ログに記録される呼び出し元の名前。"),
    ] = "mcp-client",
) -> MCPRestoreResponse:
    try:
        with SessionLocal() as db:
            restored, replayed = restore_opportunity(
                db,
                opportunity_id=opportunity_id,
                request_id=request_id,
                client_name=client_name,
            )
            return MCPRestoreResponse.model_validate(
                {
                    "success": True,
                    "idempotent_replay": replayed,
                    "message": "同じ復元操作は処理済みです" if replayed else "募集情報を復元しました",
                    "opportunity": restored,
                }
            )
    except DomainValidationError as exc:
        with SessionLocal() as db:
            record_failed_attempt(
                db,
                action="restore",
                request_id=request_id,
                client_name=client_name,
                source_url=None,
                errors=exc.errors,
            )
        raise _validation_error(client_name, request_id, exc.errors) from exc
    except LookupError as exc:
        raise _json_error({"error": "not_found", "message": "指定された削除済み募集情報が見つかりません"}) from exc


@mcp.tool(
    name="list_collection_targets",
    title="情報収集対象の企業を一覧",
    description=(
        "運営者用の情報収集対象を企業名、業界、業種、優先度、確認期限で絞り込みます。"
        "source_gap=trueで、採用・インターンページが未登録の対象だけを取り出せます。"
        "返却する募集一覧は定期再確認対象（募集予定・募集中・通年募集）だけで、締切などの終了状態は含みません。"
        "無効化済みの対象はinclude_inactive=trueの場合だけ返します。認証が必要です。"
    ),
    annotations=READ_ONLY,
)
def list_collection_targets_tool(
    query: Annotated[str | None, Field(description="企業名の部分一致キーワード。", max_length=200)] = None,
    industry: Annotated[
        IndustryValue | None,
        Field(description="業界。企業が複数業界に属する場合、そのいずれかに一致すれば該当します。省略すると全業界。"),
    ] = None,
    sector: Annotated[str | None, Field(description="業種名。")] = None,
    priority_tier: Annotated[int | None, Field(ge=1, le=3, description="内部収集優先度。1が最優先。")] = None,
    due_only: Annotated[bool, Field(description="未確認または次回確認期限を過ぎた対象だけを返します。")] = False,
    source_gap: Annotated[
        bool,
        Field(
            description=(
                "採用ページ・インターンページがまだ登録されておらず、企業トップページなどしか"
                "監視できていない対象だけを返します。公式ページを調べ直して追加する棚卸しに使います。"
            )
        ),
    ] = False,
    include_inactive: Annotated[bool, Field(description="無効化済みの対象も含めます。")] = False,
    page: Annotated[int, Field(ge=1, description="1から始まるページ番号。")] = 1,
    per_page: Annotated[int, Field(ge=1, le=50, description="1ページあたりの件数。")] = 20,
) -> MCPCollectionTargetListResponse:
    with SessionLocal() as db:
        result = list_collection_targets(
            db,
            query=query,
            industry=industry,
            sector=sector,
            priority_tier=priority_tier,
            due_only=due_only,
            source_gap=source_gap,
            include_inactive=include_inactive,
            page=page,
            per_page=per_page,
        )
        return MCPCollectionTargetListResponse.model_validate(
            {
                "items": [collection_target_dict(db, item) for item in result.items],
                "total": result.total,
                "page": result.page,
                "per_page": result.per_page,
                "total_pages": result.total_pages,
            }
        )


@mcp.tool(
    name="get_collection_target",
    title="情報収集対象を1件取得",
    description=(
        "収集対象、所属業界、公式ページ、その企業の定期再確認対象の募集をIDで取得します。"
        "締切などの終了状態の募集は一覧に含みません。認証が必要です。"
    ),
    annotations=READ_ONLY,
)
def get_collection_target_tool(
    target_id: Annotated[int, Field(ge=1, description="収集対象ID。")],
) -> CollectionTargetResponse:
    with SessionLocal() as db:
        target = get_collection_target_record(db, target_id)
        if target is None:
            raise _json_error({"error": "not_found", "message": "指定された収集対象が見つかりません"})
        return CollectionTargetResponse.model_validate(collection_target_dict(db, target))


@mcp.tool(
    name="get_company_maintenance_context",
    title="企業単位の募集保守コンテキストを取得",
    description=(
        "指定企業の定期再確認対象（募集予定・募集中・通年募集）だけを、各募集の一次情報URL・最終確認日時とともに返します。"
        "締切などの終了状態は定期保守の対象外として含めません。企業単位で登録した公式ページもまとめて返します。"
        "公式採用サイトを確認した後、複数募集を更新・確認するために使います。認証が必要です。"
    ),
    annotations=READ_ONLY,
)
def get_company_maintenance_context_tool(
    company_id: Annotated[int, Field(ge=1, description="対象企業のID。resolve_companyなどが返すidを指定します。")],
) -> MCPCompanyMaintenanceContextResponse:
    with SessionLocal() as db:
        context = get_company_maintenance_context(db, company_id)
        if context is None:
            raise _json_error({"error": "not_found", "message": "指定された企業が見つかりません"})
        company, target, opportunities = context
        return MCPCompanyMaintenanceContextResponse.model_validate(
            {
                "company": company_identity_dict(company),
                "collection_target_id": target.id if target else None,
                "collection_last_checked_at": target.last_checked_at if target else None,
                "official_sources": [
                    collection_source_dict(source)
                    for source in sorted(target.sources, key=lambda value: (not value.is_active, value.id))
                ]
                if target
                else [],
                "opportunities": [
                    {
                        "id": item.id,
                        "public_code": item.public_code,
                        "url": detail_url(item),
                        "event_name": item.event_name,
                        "recruitment_status": item.status.name,
                        "graduation_years": [
                            value.name for value in sorted(item.graduation_years, key=lambda value: value.sort_order)
                        ],
                        "deadline": item.deadline,
                        "event_end_date": item.event_end_date,
                        "source_url": item.source_url,
                        "source_checked_at": item.source_checked_at,
                        "updated_at": item.updated_at,
                    }
                    for item in opportunities
                ],
            }
        )


@mcp.tool(
    name="list_unmonitored_companies",
    title="収集対象が未作成の企業を一覧",
    description=(
        "企業マスタには存在するものの、まだ収集対象を持たない企業を返します。"
        "返されたidをadd_collection_targetのcompany_idへ指定すると、名称の再入力や表記ゆれなしで監視対象へ追加できます。"
        "認証が必要です。"
    ),
    annotations=READ_ONLY,
)
def list_unmonitored_companies_tool(
    query: Annotated[str | None, Field(description="企業名または登録済み別名の部分一致キーワード。", max_length=200)] = None,
    industry: Annotated[IndustryValue | None, Field(description="企業分類の業界。省略すると全業界。")] = None,
    page: Annotated[int, Field(ge=1, description="1から始まるページ番号。")] = 1,
    per_page: Annotated[int, Field(ge=1, le=50, description="1ページあたりの件数。")] = 20,
) -> MCPUnmonitoredCompanyListResponse:
    with SessionLocal() as db:
        result = list_unmonitored_companies(db, query=query, industry=industry, page=page, per_page=per_page)
        return MCPUnmonitoredCompanyListResponse.model_validate(
            {
                "items": [unmonitored_company_dict(item) for item in result.items],
                "total": result.total,
                "page": result.page,
                "per_page": result.per_page,
                "total_pages": result.total_pages,
            }
        )


@mcp.tool(
    name="get_collection_queue",
    title="次に確認する企業を取得",
    description=(
        "有効な収集対象から、未確認または確認期限を過ぎた企業を優先度順に返します。"
        "返却する募集一覧は定期再確認対象（募集予定・募集中・通年募集）だけで、締切などの終了状態は含みません。"
        "募集一覧が空の企業も、新しい募集を発見するために返します。"
        "各公式ページを確認し、募集の有無にかかわらずrecord_collection_checkを実行してください。認証が必要です。"
    ),
    annotations=READ_ONLY,
)
def get_collection_queue_tool(
    industry: Annotated[IndustryValue | None, Field(description="対象業界。省略すると全業界。")] = None,
    limit: Annotated[int, Field(ge=1, le=50, description="取得件数。")] = 20,
) -> MCPCollectionQueueResponse:
    with SessionLocal() as db:
        items = collection_queue(db, industry=industry, limit=limit)
        return MCPCollectionQueueResponse.model_validate(
            {"items": [collection_target_dict(db, item) for item in items]}
        )


@mcp.tool(
    name="list_undercovered_companies",
    title="紐付く募集が少ない収集対象を取得",
    description=(
        "有効な収集対象を、その企業に紐づく募集情報が少ない順（0件を優先）に返します。"
        "募集件数は定期再確認対象（募集予定・募集中・通年募集）だけを数え、締切などの終了状態は除外します。"
        "「情報の少ない企業を優先して確認したい」場合に、get_collection_queueの結果をopportunitiesが"
        "空かどうかで絞り込む代わりに使います。認証が必要です。"
    ),
    annotations=READ_ONLY,
)
def list_undercovered_companies_tool(
    industry: Annotated[IndustryValue | None, Field(description="対象業界。省略すると全業界。")] = None,
    limit: Annotated[int, Field(ge=1, le=50, description="取得件数。")] = 20,
) -> MCPCollectionQueueResponse:
    with SessionLocal() as db:
        items = undercovered_collection_targets(db, industry=industry, limit=limit)
        return MCPCollectionQueueResponse.model_validate(
            {"items": [collection_target_dict(db, item) for item in items]}
        )


@mcp.tool(
    name="list_collection_checks",
    title="情報収集の確認履歴を取得",
    description="指定した収集対象について、募集あり・なし・確認不能などの確認履歴を新しい順に返します。認証が必要です。",
    annotations=READ_ONLY,
)
def list_collection_checks_tool(
    target_id: Annotated[int, Field(ge=1, description="収集対象ID。")],
    limit: Annotated[int, Field(ge=1, le=100, description="取得件数。")]=20,
) -> MCPCollectionCheckListResponse:
    try:
        with SessionLocal() as db:
            items = list_collection_checks(db, target_id=target_id, limit=limit)
            return MCPCollectionCheckListResponse.model_validate(
                {"items": [collection_check_dict(item) for item in items]}
            )
    except LookupError as exc:
        raise _json_error({"error": "not_found", "message": "指定された収集対象が見つかりません"}) from exc


@mcp.tool(
    name="add_collection_target",
    title="情報収集対象を追加",
    description=(
        "既存CompanyのIDまたは新規企業の正式名と、所属業界を内部の収集キューへ追加します。企業公式ページを1件以上指定します。"
        "priority_tierは企業評価ではなく確認順です。tier1は最優先で毎回確認する少数のリストなので"
        "上限（200社）に達している間はtier1で追加できません。tier2以下で登録するか、"
        "既存のtier1対象を見直してから再試行してください。認証が必要です。"
    ),
    annotations=APPEND_ONLY,
)
def add_collection_target_tool(payload: CollectionTargetCreatePayload) -> MCPCollectionWriteResponse:
    request = _parse_collection_payload(payload, CollectionTargetCreateRequest, "collection_target_create")
    try:
        with SessionLocal() as db:
            target, replayed = create_collection_target(db, request)
            return MCPCollectionWriteResponse.model_validate(
                {
                    "success": True,
                    "idempotent_replay": replayed,
                    "message": "情報収集対象を追加しました",
                    "target": collection_target_dict(db, target),
                }
            )
    except DomainValidationError as exc:
        raise _collection_domain_error(request, "collection_target_create", exc) from exc
    except LookupError as exc:
        raise _json_error({"error": "not_found", "message": "指定された既存Companyが見つかりません"}) from exc


@mcp.tool(
    name="update_collection_target",
    title="情報収集対象を部分更新",
    description=(
        "指定した項目だけを変更します。sectorまたはselection_reasonをnullにすると値を解除できます。"
        "削除の代わりにis_active=falseで収集対象から外せます。認証が必要です。"
    ),
    annotations=PATCHING,
)
def update_collection_target_tool(
    target_id: Annotated[int, Field(ge=1, description="更新する収集対象ID。")],
    payload: CollectionTargetUpdatePayload,
) -> MCPCollectionWriteResponse:
    request = _parse_collection_payload(payload, CollectionTargetUpdateRequest, "collection_target_update")
    try:
        with SessionLocal() as db:
            target, replayed = update_collection_target(db, target_id=target_id, payload=request)
            return MCPCollectionWriteResponse.model_validate(
                {
                    "success": True,
                    "idempotent_replay": replayed,
                    "message": "情報収集対象を更新しました",
                    "target": collection_target_dict(db, target),
                }
            )
    except DomainValidationError as exc:
        raise _collection_domain_error(request, "collection_target_update", exc) from exc
    except LookupError as exc:
        raise _json_error({"error": "not_found", "message": "指定された収集対象が見つかりません"}) from exc


@mcp.tool(
    name="add_collection_source",
    title="企業公式ページを追加",
    description="既存の収集対象へ確認先となる企業公式ページを追加します。認証が必要です。",
    annotations=APPEND_ONLY,
)
def add_collection_source_tool(
    target_id: Annotated[int, Field(ge=1, description="追加先の収集対象ID。")],
    payload: CollectionSourceCreatePayload,
) -> MCPCollectionSourceWriteResponse:
    request = _parse_collection_payload(payload, CollectionSourceCreateRequest, "collection_source_create")
    try:
        with SessionLocal() as db:
            source, replayed = create_collection_source(db, target_id=target_id, payload=request)
            return MCPCollectionSourceWriteResponse.model_validate(
                {
                    "success": True,
                    "idempotent_replay": replayed,
                    "message": "企業公式ページを追加しました",
                    "source": collection_source_dict(source),
                }
            )
    except DomainValidationError as exc:
        raise _collection_domain_error(request, "collection_source_create", exc) from exc
    except LookupError as exc:
        raise _json_error({"error": "not_found", "message": "指定された収集対象が見つかりません"}) from exc


@mcp.tool(
    name="update_collection_source",
    title="企業公式ページを部分更新",
    description="URL、種類、有効状態のうち指定した項目だけを変更します。認証が必要です。",
    annotations=PATCHING,
)
def update_collection_source_tool(
    source_id: Annotated[int, Field(ge=1, description="更新する公式ページID。")],
    payload: CollectionSourceUpdatePayload,
) -> MCPCollectionSourceWriteResponse:
    request = _parse_collection_payload(payload, CollectionSourceUpdateRequest, "collection_source_update")
    try:
        with SessionLocal() as db:
            source, replayed = update_collection_source(db, source_id=source_id, payload=request)
            return MCPCollectionSourceWriteResponse.model_validate(
                {
                    "success": True,
                    "idempotent_replay": replayed,
                    "message": "企業公式ページを更新しました",
                    "source": collection_source_dict(source),
                }
            )
    except DomainValidationError as exc:
        raise _collection_domain_error(request, "collection_source_update", exc) from exc
    except LookupError as exc:
        raise _json_error({"error": "not_found", "message": "指定された公式ページが見つかりません"}) from exc


@mcp.tool(
    name="record_collection_check",
    title="企業公式ページの確認結果を記録",
    description=(
        "募集を発見した場合だけでなく、募集中なし、ページ確認不能、人の確認が必要な場合も履歴へ記録し、"
        "次回確認日を更新します。実際に確認したsource_urlが募集自身または登録済み公式sourceと一致するか検証します。"
        "確認中に採用ページなどを新しく見つけた場合はdiscovered_sourcesへ渡すと"
        "同時に情報源として追加します。認証が必要です。"
    ),
    annotations=APPEND_ONLY,
)
def record_collection_check_tool(
    target_id: Annotated[int, Field(ge=1, description="確認した収集対象ID。")],
    payload: CollectionCheckPayload,
) -> MCPCollectionCheckWriteResponse:
    request = _parse_collection_payload(payload, CollectionCheckRequest, "collection_check_create")
    try:
        with SessionLocal() as db:
            check, target, replayed = record_collection_check(db, target_id=target_id, payload=request)
            return MCPCollectionCheckWriteResponse.model_validate(
                {
                    "success": True,
                    "idempotent_replay": replayed,
                    "message": "確認結果と次回確認日を記録しました",
                    "check": collection_check_dict(check),
                    "target": collection_target_dict(db, target),
                }
            )
    except DomainValidationError as exc:
        raise _collection_domain_error(request, "collection_check_create", exc) from exc
    except LookupError as exc:
        raise _json_error({"error": "not_found", "message": "指定された収集対象が見つかりません"}) from exc


@mcp.tool(
    title="直近の書き込み履歴を取得",
    description=(
        "自分を含むクライアントによる直近の登録・更新・削除・復元の記録を返します。"
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


@mcp.tool(
    name="list_stale_opportunities",
    title="要確認の募集を優先順に取得",
    description=(
        "定期再確認対象（募集予定・募集中・通年募集）だけを返します。"
        "そのうち「募集中」なのに締め切りまたは実施終了日を過ぎた矛盾を最優先で返します。"
        "続いて公式ページを一定期間確認できていない募集を、未確認・確認日が古い順に返します。締切などの終了状態は含みません。"
        "矛盾は自動で「締切」に変更しません。"
        "見つけた各募集はupdate_recruitment_status、patch_opportunity、"
        "変更がなければverify_opportunity、収集対象があるならrecord_collection_checkで再確認結果を記録してください。認証が必要です。"
    ),
    annotations=READ_ONLY,
)
def list_stale_opportunities_tool(
    days: Annotated[
        int,
        Field(
            ge=1,
            le=365,
            description="この日数より公式情報の確認が経過している募集を対象にします。日付と「募集中」の矛盾は日数にかかわらず含まれます。",
        ),
    ] = 7,
    limit: Annotated[int, Field(ge=1, le=100, description="取得件数（1〜100）。")] = 20,
) -> MCPStaleOpportunityListResponse:
    with SessionLocal() as db:
        reviews = list_opportunities_requiring_review(db, days=days, limit=limit)
        return MCPStaleOpportunityListResponse.model_validate(
            {
                "items": [
                    opportunity_summary(review.opportunity) | {"review_reasons": review.reasons}
                    for review in reviews
                ]
            }
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
                    [{"type": "noauth"}] if tool.name in ANONYMOUS_TOOLS else [{"type": "oauth2", "scopes": ["mcp"]}]
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
