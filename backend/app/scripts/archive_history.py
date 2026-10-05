"""Archive expired audit, retry, collection, and OAuth history."""

import sys

from app.db import SessionLocal
from app.services.history_archive import archive_expired_history


def run() -> int:
    with SessionLocal() as db:
        result = archive_expired_history(db)
    print(
        f"archived_audit={result.archived_audit} "
        f"archived_checks={result.archived_checks} "
        f"archived_idempotency={result.archived_idempotency} "
        f"archived_company_requests={result.archived_company_requests} "
        f"archived_collection_requests={result.archived_collection_requests} "
        f"archived_oauth_tokens={result.archived_oauth_tokens}"
    )
    return 0


def main() -> int:
    try:
        return run()
    except Exception:
        print("history_archive_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
