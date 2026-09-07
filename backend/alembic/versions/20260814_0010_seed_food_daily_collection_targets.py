"""Seed food and daily-goods manufacturers into the internal collection queue."""

import base64
import hashlib
import json
import re
import secrets
import unicodedata
import zlib

import sqlalchemy as sa

from alembic import op

revision = "20260814_0010"
down_revision = "20260814_0009"
branch_labels = None
depends_on = None

CLIENT = "migration-food-daily-20260814"
REASONS = {
    "食品": "食品メーカーの企業カバレッジを拡充し、新卒採用・インターン情報を継続確認するため。",
    "日用品": "日用品・生活消費財メーカーの企業カバレッジを拡充し、新卒採用・インターン情報を継続確認するため。",
}
# Compressed JSON keeps this one-time data migration compact while retaining the curated 180-company payload.
PAYLOAD = (
    "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"
    "pOJHaApldCQlVjm//B8ebOIS"
)


def _entries() -> list[list[str]]:
    raw = zlib.decompress(base64.b64decode(PAYLOAD)).decode("utf-8")
    return json.loads(raw)


# Kept in sync with app.models on purpose: a migration must not depend on today's application code.
PUBLIC_CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PUBLIC_CODE_LENGTH = 8


def _company_public_code(bind: sa.Connection) -> str:
    """A free public code for a company row this seed creates.

    companies.public_code is added by revision 20260907_0014 and has only a Python-side default, so
    a fresh database - where revision 0001 already built the column from live metadata - needs the
    code supplied here. An upgraded database reaches this revision before the column exists and
    skips it; see _has_company_public_code.
    """
    for _ in range(10):
        code = "".join(secrets.choice(PUBLIC_CODE_ALPHABET) for _ in range(PUBLIC_CODE_LENGTH))
        if _scalar(bind, "SELECT id FROM companies WHERE public_code=:code", code=code) is None:
            return code
    raise RuntimeError("failed to generate a company public code")


def _has_company_public_code(bind: sa.Connection) -> bool:
    return "public_code" in {column["name"] for column in sa.inspect(bind).get_columns("companies")}


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[（(](?:株)[）)]|㈱", "株式会社", value)
    return value.replace("株式会社", "").replace("有限会社", "").casefold()


def _scalar(bind: sa.Connection, sql: str, **params: object) -> object | None:
    return bind.execute(sa.text(sql), params).scalar_one_or_none()


def _classification_on_targets(bind: sa.Connection) -> bool:
    """Whether collection_targets still carries the classification itself.

    Revision 0001 builds fresh databases from the live metadata, so on a fresh install this seed
    already runs against the post-20260820_0012 schema - one target per company, classification in
    company_industries - while an upgraded database reaches it with the old columns still present.
    """
    return "industry_id" in {column["name"] for column in sa.inspect(bind).get_columns("collection_targets")}


def _classify(bind: sa.Connection, *, company_id: int, industry_id: int, sector_id: int) -> None:
    existing = _scalar(
        bind,
        "SELECT id FROM company_industries WHERE company_id=:company_id AND industry_id=:industry_id",
        company_id=company_id,
        industry_id=industry_id,
    )
    if existing is not None:
        bind.execute(
            sa.text("UPDATE company_industries SET sector_id=:sector_id WHERE id=:id"),
            {"sector_id": sector_id, "id": int(existing)},
        )
        return
    has_primary = _scalar(
        bind,
        "SELECT id FROM company_industries WHERE company_id=:company_id AND is_primary",
        company_id=company_id,
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO company_industries (company_id, industry_id, sector_id, is_primary)
            VALUES (:company_id, :industry_id, :sector_id, :is_primary)
            """
        ),
        {
            "company_id": company_id,
            "industry_id": industry_id,
            "sector_id": sector_id,
            "is_primary": has_primary is None,
        },
    )


def _record(
    bind: sa.Connection,
    *,
    action: str,
    entity_type: str,
    entity_id: int,
    request_id: str,
    source_url: str,
    payload: dict[str, object],
) -> None:
    request_hash = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()
    bind.execute(
        sa.text(
            """
            INSERT INTO collection_request_records
                (request_id, operation, request_hash, entity_type, entity_id)
            VALUES (:request_id, :action, :request_hash, :entity_type, :entity_id)
            """
        ),
        {
            "request_id": request_id,
            "action": action,
            "request_hash": request_hash,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
        },
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO audit_logs
                (action, entity_type, entity_id, request_id, client_name, source_url, success)
            VALUES (:action, :entity_type, :entity_id, :request_id, :client, :source_url, true)
            """
        ),
        {
            "action": action,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "request_id": request_id,
            "client": CLIENT,
            "source_url": source_url,
        },
    )


def upgrade() -> None:
    bind = op.get_bind()
    legacy = _classification_on_targets(bind)
    with_public_code = _has_company_public_code(bind)
    industry_id = _scalar(bind, "SELECT id FROM industries WHERE name='メーカー'")
    if industry_id is None:
        raise RuntimeError("メーカー industry master is missing")

    sectors = {}
    for name in ("食品", "日用品"):
        sector_id = _scalar(
            bind,
            "SELECT id FROM sectors WHERE industry_id=:industry_id AND name=:name",
            industry_id=industry_id,
            name=name,
        )
        if sector_id is None:
            raise RuntimeError(f"{name} sector master is missing under メーカー")
        sectors[name] = int(sector_id)

    created = reclassified = sources_added = covered = 0
    for index, (company_name, sector_name, source_url) in enumerate(_entries(), 1):
        normalized = _normalize(company_name)
        company_id = _scalar(
            bind,
            """
            SELECT id FROM companies
            WHERE normalized_name=:normalized OR name=:name
            ORDER BY CASE WHEN normalized_name=:normalized THEN 0 ELSE 1 END
            LIMIT 1
            """,
            normalized=normalized,
            name=company_name,
        )
        if company_id is None:
            if with_public_code:
                bind.execute(
                    sa.text(
                        "INSERT INTO companies (name, normalized_name, public_code) "
                        "VALUES (:name, :normalized, :public_code)"
                    ),
                    {
                        "name": company_name,
                        "normalized": normalized,
                        "public_code": _company_public_code(bind),
                    },
                )
            else:
                bind.execute(
                    sa.text("INSERT INTO companies (name, normalized_name) VALUES (:name, :normalized)"),
                    {"name": company_name, "normalized": normalized},
                )
            company_id = _scalar(
                bind,
                "SELECT id FROM companies WHERE normalized_name=:normalized",
                normalized=normalized,
            )
        if company_id is None:
            raise RuntimeError(f"failed to resolve company: {company_name}")
        company_id = int(company_id)

        target = bind.execute(
            sa.text(
                "SELECT id, sector_id FROM collection_targets "
                "WHERE company_id=:company_id AND industry_id=:industry_id"
                if legacy
                else """
                SELECT ct.id AS id, ci.sector_id AS sector_id
                FROM collection_targets ct
                LEFT JOIN company_industries ci
                  ON ci.company_id = ct.company_id AND ci.industry_id = :industry_id
                WHERE ct.company_id = :company_id
                """
            ),
            {"company_id": company_id, "industry_id": industry_id},
        ).mappings().one_or_none()
        target_created = target is None
        desired_sector = sectors[sector_name]
        priority = 1 if index <= 20 or 119 <= index <= 138 else 2
        interval = 7 if priority == 1 else 14

        if target_created:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO collection_targets
                        (
                            company_id, industry_id, sector_id, priority_tier,
                            check_interval_days, is_active, selection_reason
                        )
                    VALUES
                        (:company_id, :industry_id, :sector_id, :priority, :interval, true, :reason)
                    """
                    if legacy
                    else """
                    INSERT INTO collection_targets
                        (company_id, priority_tier, check_interval_days, is_active, selection_reason)
                    VALUES (:company_id, :priority, :interval, true, :reason)
                    """
                ),
                {
                    "company_id": company_id,
                    "industry_id": industry_id,
                    "sector_id": desired_sector,
                    "priority": priority,
                    "interval": interval,
                    "reason": REASONS[sector_name],
                }
                if legacy
                else {
                    "company_id": company_id,
                    "priority": priority,
                    "interval": interval,
                    "reason": REASONS[sector_name],
                },
            )
            if not legacy:
                _classify(bind, company_id=company_id, industry_id=industry_id, sector_id=desired_sector)
            target_id = _scalar(
                bind,
                "SELECT id FROM collection_targets WHERE company_id=:company_id AND industry_id=:industry_id"
                if legacy
                else "SELECT id FROM collection_targets WHERE company_id=:company_id",
                company_id=company_id,
                **({"industry_id": industry_id} if legacy else {}),
            )
            if target_id is None:
                raise RuntimeError(f"failed to create target: {company_name}")
            target_id = int(target_id)
            created += 1
            request_id = f"migration-food-daily-20260814-target-{index:03d}"
            _record(
                bind,
                action="collection_target_create",
                entity_type="collection_target",
                entity_id=target_id,
                request_id=request_id,
                source_url=source_url,
                payload={"company": company_name, "sector": sector_name, "url": source_url},
            )
        else:
            target_id = int(target["id"])
            if target["sector_id"] != desired_sector:
                if legacy:
                    bind.execute(
                        sa.text(
                            "UPDATE collection_targets "
                            "SET sector_id=:sector_id, updated_at=CURRENT_TIMESTAMP WHERE id=:id"
                        ),
                        {"sector_id": desired_sector, "id": target_id},
                    )
                else:
                    _classify(bind, company_id=company_id, industry_id=industry_id, sector_id=desired_sector)
                reclassified += 1
                request_id = f"migration-food-daily-20260814-update-{index:03d}"
                _record(
                    bind,
                    action="collection_target_update",
                    entity_type="collection_target",
                    entity_id=target_id,
                    request_id=request_id,
                    source_url=source_url,
                    payload={"target_id": target_id, "sector": sector_name},
                )

        source_id = _scalar(
            bind,
            "SELECT id FROM collection_sources WHERE collection_target_id=:target_id AND url=:url",
            target_id=target_id,
            url=source_url,
        )
        if source_id is None:
            source_type = "recruit" if "recruit" in source_url else "other"
            bind.execute(
                sa.text(
                    """
                    INSERT INTO collection_sources (collection_target_id, source_type, url, is_active)
                    VALUES (:target_id, :source_type, :url, true)
                    """
                ),
                {"target_id": target_id, "source_type": source_type, "url": source_url},
            )
            sources_added += 1
            if not target_created:
                source_id = _scalar(
                    bind,
                    "SELECT id FROM collection_sources WHERE collection_target_id=:target_id AND url=:url",
                    target_id=target_id,
                    url=source_url,
                )
                if source_id is None:
                    raise RuntimeError(f"failed to create source: {company_name}")
                request_id = f"migration-food-daily-20260814-source-{index:03d}"
                _record(
                    bind,
                    action="collection_source_create",
                    entity_type="collection_source",
                    entity_id=int(source_id),
                    request_id=request_id,
                    source_url=source_url,
                    payload={"target_id": target_id, "type": source_type, "url": source_url},
                )
        elif not target_created and target["sector_id"] == desired_sector:
            covered += 1

    print(
        "food/daily collection seed:"
        f" targets_created={created}, targets_reclassified={reclassified},"
        f" sources_added={sources_added}, already_covered={covered}"
    )


def downgrade() -> None:
    # Curated operational data may be enriched or linked to opportunities after deployment.
    pass
