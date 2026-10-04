"""Read recorded MCP write outcomes, with execution filters and counts across all pages."""

from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import AuditLog
from app.services.serialization import public_detail_url


def recent_write_logs(
    db: Session,
    *,
    client_name: str | None = None,
    entity_type: str | None = None,
    run_id: str | None = None,
    limit: int = 20,
    page: int = 1,
) -> dict[str, Any]:
    """Recent MCP writes of every entity_type (opportunity, company, collection_*), successes and rejections alike.

    ``opportunity_id`` and ``url`` are filled only for opportunity rows.
    """
    stmt = select(AuditLog)
    if client_name:
        stmt = stmt.where(AuditLog.client_name == client_name)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if run_id is not None:
        stmt = stmt.where(AuditLog.run_id == run_id)
    recorded_unknown = func.coalesce(AuditLog.errors[0]["code"].as_string(), "") == "internal_error"
    counts = db.execute(
        stmt.with_only_columns(
            func.count(AuditLog.id),
            func.coalesce(func.sum(case((AuditLog.success.is_(True), 1), else_=0)), 0),
            func.coalesce(func.sum(case((AuditLog.success.is_(False) & ~recorded_unknown, 1), else_=0)), 0),
            func.coalesce(func.sum(case((AuditLog.success.is_(False) & recorded_unknown, 1), else_=0)), 0),
        )
    ).one()
    logs = db.scalars(
        stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset((page - 1) * limit).limit(limit)
    )
    items = []
    for log in logs:
        outcome = "succeeded"
        if not log.success:
            outcome = "unknown" if (log.errors or [{}])[0].get("code") == "internal_error" else "rejected"
        is_opportunity = log.entity_type == "opportunity"
        # A company snapshot carries its own public_code, which is not an opportunity detail page.
        public_code = ((log.changes or {}).get("after") or {}).get("public_code") if is_opportunity else None
        items.append(
            {
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "request_id": log.request_id,
                "run_id": log.run_id,
                "client_name": log.client_name,
                "success": log.success,
                "outcome": outcome,
                "opportunity_id": log.entity_id if is_opportunity else None,
                "url": public_detail_url(public_code) if public_code else None,
                "source_url": log.source_url,
                "errors": log.errors,
                "created_at": log.created_at,
            }
        )
    return {
        "items": items,
        "total_count": counts[0],
        "succeeded_count": counts[1],
        "failed_count": counts[2],
        "unknown_count": counts[3],
        "page": page,
        "has_more": page * limit < counts[0],
    }
