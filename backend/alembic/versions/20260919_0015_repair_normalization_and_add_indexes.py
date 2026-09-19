"""Repair data drift from earlier revisions and add indexes app.models has grown since.

Three unrelated repairs, bundled into one revision because none of them changes the schema shape by
itself and all three are one-time cleanups over the current data:

1. The 20260814_0010 seed migration's own copy of the company-name normalizer never stripped "・"
   (nakaguro), while app.services.normalization.normalize_company_name always has. Four of the 180
   seeded companies (e.g. "コカ・コーラ ボトラーズジャパン株式会社") were stored with a
   normalized_name the application would never itself produce, which makes find_company miss them
   and get_or_create_company either 500 on the companies.name UNIQUE constraint or - worse - insert
   a second Company row with a different spelling of the same company. This re-normalizes every
   existing companies.normalized_name / company_aliases.normalized_alias with today's rule.
2. Migration 20260820_0012 merged duplicate collection_targets rows by taking
   MAX(last_checked_at) but leaving the keeper's own (often NULL) last_check_result behind, so a
   target that had in fact just been checked reads as "needs_review". This re-derives
   last_check_result from each target's own most recent CollectionCheck row, which the same
   migration preserved by re-pointing checks at the keeper before deleting the loser.
3. Before this branch's fix to services/companies.py's _merge_collection_targets,
   collection_request_records rows naming a merged-away collection_target/collection_source were
   left dangling: replaying that request_id resolves an id that no longer exists and
   get_collection_target/get_collection_source raise RuntimeError - a 500 for what is supposed to be
   a silent no-op. There is no record of which surviving id a historical merge chose (no merge log
   was ever kept), so those dangling rows cannot be remapped after the fact; they are removed
   instead, which only means a very late retry of an already-completed request is treated as new
   (the same outcome an operator already gets today, just as a validation error instead of a 500)
   rather than continuing to fail hard.

Also adds the indexes app.models now declares that no earlier revision created: opportunities had no
index on company_id (every company-scoped read - the public company page, the collection queue's
coverage subqueries, merge_company's row lock - relied on a full table scan) or on either of its two
listing sort orders, and collection_checks had no index supporting "latest N checks for one target".
"""

import logging
import re
import unicodedata

import sqlalchemy as sa

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision = "20260919_0015"
down_revision = "20260907_0014"
branch_labels = None
depends_on = None


# Kept in sync with app.services.normalization.normalize_company_name on purpose: a migration must
# not depend on today's application code, which is free to change independently of already-shipped
# revisions. If normalize_company_name changes again, add a fresh migration rather than editing this
# copy or this one.
def _normalize_company_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[（(](?:株)[）)]|㈱", "株式会社", value)
    without_legal = value.replace("株式会社", "").replace("有限会社", "")
    without_legal = without_legal.replace("・", "")
    return without_legal.casefold()


def _apply_renormalization(
    bind: sa.Connection,
    *,
    table: str,
    column: str,
    rows: list,
    wanted: dict,
    label: str,
) -> None:
    """Write the corrected values, skipping any group that would collide.

    Two rows normalizing to the same value under the corrected rule are the same company under two
    spellings - precisely the duplicate the missing "・" strip let through get_or_create_company.
    Merging them here would mean reimplementing merge_company's transactional, audited handling of
    collection targets/sources/checks, aliases, opportunities and request-record remapping a second
    time in raw SQL, untested.

    This used to raise instead, on the reasoning that an operator should resolve each group with
    merge_company first. That was wrong for where this code runs: the api container's command is
    `alembic upgrade head && uvicorn ...`, so a raise here does not surface a data-quality report -
    it stops the API from starting at all, and takes the site down with it. The rows that would
    collide are left exactly as they are (no worse than before this revision) and named in the log;
    every other row is repaired. Resolving the named groups with merge_company and re-running is
    still the right follow-up, but it is no longer an outage.

    The writes go out in two passes because a corrected value can also collide transiently with the
    *current* value of a row that is itself about to change. Parking every changing row on a unique
    placeholder first makes the result independent of update order.
    """
    ids_by_new_value: dict[str, list[int]] = {}
    for row in rows:
        ids_by_new_value.setdefault(wanted[row.id], []).append(row.id)

    collisions = {value: ids for value, ids in ids_by_new_value.items() if len(ids) > 1}
    skipped: set[int] = set()
    if collisions:
        skipped = {row_id for ids in collisions.values() for row_id in ids}
        details = "; ".join(f"{value!r} <- {label} ids {ids}" for value, ids in collisions.items())
        logger.warning(
            "20260919_0015: leaving %d %s row(s) un-normalized because the corrected rule would "
            "collide between existing rows (%s). These are duplicate records of the same company "
            "under two spellings; resolve each group with merge_company (see "
            "app/services/companies.py) and re-run this repair. Every other row was repaired.",
            len(skipped),
            label,
            details,
        )

    changing = [row for row in rows if row.id not in skipped and wanted[row.id] != getattr(row, column)]
    for row in changing:
        bind.execute(
            sa.text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
            {"value": f"__0015_migrating__{row.id}", "id": row.id},
        )
    for row in changing:
        bind.execute(
            sa.text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
            {"value": wanted[row.id], "id": row.id},
        )


def _renormalize_companies(bind: sa.Connection) -> None:
    rows = bind.execute(sa.text("SELECT id, name, normalized_name FROM companies")).fetchall()
    wanted = {row.id: _normalize_company_name(row.name) for row in rows}
    _apply_renormalization(
        bind, table="companies", column="normalized_name", rows=rows, wanted=wanted, label="company"
    )


def _renormalize_company_aliases(bind: sa.Connection) -> None:
    # normalized_alias is unique across the whole table, not just per company, so a collision here
    # can also occur between two aliases of two different companies.
    rows = bind.execute(sa.text("SELECT id, alias, normalized_alias FROM company_aliases")).fetchall()
    wanted = {row.id: _normalize_company_name(row.alias) for row in rows}
    _apply_renormalization(
        bind,
        table="company_aliases",
        column="normalized_alias",
        rows=rows,
        wanted=wanted,
        label="company_alias",
    )


def _repair_merged_check_results(bind: sa.Connection) -> None:
    """Re-derive last_check_result from each target's own latest CollectionCheck row.

    A target whose last_checked_at is set but whose last_check_result disagrees with (or predates)
    its own most recent check is exactly the corruption 20260820_0012's merge left behind - the two
    fields describe one event and must move together, which the live _merge_collection_targets path
    now enforces going forward.
    """
    bind.execute(
        sa.text(
            """
            UPDATE collection_targets
            SET last_check_result = (
                SELECT cc.result FROM collection_checks cc
                WHERE cc.collection_target_id = collection_targets.id
                ORDER BY cc.checked_at DESC, cc.id DESC
                LIMIT 1
            )
            WHERE EXISTS (
                SELECT 1 FROM collection_checks cc WHERE cc.collection_target_id = collection_targets.id
            )
            AND last_check_result IS DISTINCT FROM (
                SELECT cc.result FROM collection_checks cc
                WHERE cc.collection_target_id = collection_targets.id
                ORDER BY cc.checked_at DESC, cc.id DESC
                LIMIT 1
            )
            """
        )
    )


def _drop_dangling_collection_request_records(bind: sa.Connection) -> None:
    """Remove idempotency rows naming a collection_target/collection_source merged away in the past.

    No merge log exists to say which surviving id a historical merge chose, so these cannot be
    remapped after the fact. Left in place they turn a very late retry of an already-completed
    request into a 500 (get_collection_target/get_collection_source raising RuntimeError); removed,
    the same retry is simply treated as a new request instead.
    """
    bind.execute(
        sa.text(
            """
            DELETE FROM collection_request_records
            WHERE entity_type = 'collection_target'
              AND entity_id NOT IN (SELECT CAST(id AS TEXT) FROM collection_targets)
            """
        )
    )
    bind.execute(
        sa.text(
            """
            DELETE FROM collection_request_records
            WHERE entity_type = 'collection_source'
              AND entity_id NOT IN (SELECT CAST(id AS TEXT) FROM collection_sources)
            """
        )
    )


def _index_exists(bind: sa.Connection, index_name: str, table_name: str) -> bool:
    """Whether index_name already exists on table_name.

    sa.inspect(...).get_indexes() cannot be used here: SQLAlchemy's SQLite reflection silently
    drops any expression-based index (e.g. ix_opportunities_deadline_sort's "(deadline IS NULL)")
    from the returned list instead of reporting it, which would make this migration try to create
    it a second time on a fresh database and fail on the resulting name collision. Querying each
    dialect's own catalog directly sees every index regardless of what it is built from.
    """
    if bind.dialect.name == "sqlite":
        row = bind.execute(
            sa.text("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = :name"),
            {"name": index_name},
        ).first()
    else:
        row = bind.execute(
            sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :name AND tablename = :table_name"),
            {"name": index_name, "table_name": table_name},
        ).first()
    return row is not None


# (index_name, table_name, columns) for every index this revision adds. Revision 0001 builds a
# fresh database from today's live app.models metadata (see its own docstring / 20260907_0014's),
# so a fresh install already has every one of these by the time this revision runs; only a database
# upgraded from before app.models grew them needs them created here.
NEW_INDEXES: tuple[tuple[str, str, list[object]], ...] = (
    # PostgreSQL does not index a foreign key column on its own; company_id is the join key for
    # the public company page, the collection queue's coverage subqueries, and merge_company's
    # SELECT ... FOR UPDATE.
    ("ix_opportunities_company", "opportunities", ["company_id"]),
    # Spelled exactly as services.opportunities emits each ORDER BY, so the whole sort can be
    # answered from the index instead of sorting the table.
    ("ix_opportunities_updated_sort", "opportunities", [sa.text("updated_at DESC"), "id"]),
    ("ix_opportunities_created_sort", "opportunities", [sa.text("created_at DESC"), "id"]),
    (
        "ix_opportunities_deadline_sort",
        "opportunities",
        [sa.text("(deadline IS NULL)"), "deadline", "id"],
    ),
    # Supports "latest 20 checks for one target" (list_collection_checks) and the FK scan a company
    # merge does when moving one target's rows onto another.
    (
        "ix_collection_checks_target_checked",
        "collection_checks",
        ["collection_target_id", sa.text("checked_at DESC")],
    ),
)


def upgrade() -> None:
    bind = op.get_bind()

    _renormalize_companies(bind)
    _renormalize_company_aliases(bind)
    _repair_merged_check_results(bind)
    _drop_dangling_collection_request_records(bind)

    for index_name, table_name, columns in NEW_INDEXES:
        if _index_exists(bind, index_name, table_name):
            continue
        op.create_index(index_name, table_name, columns)


def downgrade() -> None:
    bind = op.get_bind()
    for index_name, table_name, _columns in reversed(NEW_INDEXES):
        if _index_exists(bind, index_name, table_name):
            op.drop_index(index_name, table_name=table_name)
    # The renormalization and the two repair/cleanup steps are not reversible: the pre-fix
    # normalized values, the pre-repair last_check_result values, and the deleted dangling
    # collection_request_records rows are not recoverable, and reintroducing any of them would be
    # wrong even if they were.
