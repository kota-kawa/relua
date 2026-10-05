import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from app.models import CollectionTarget
from app.schemas import OpportunityInput
from app.services.opportunities import write_opportunity
from tests.test_validation import valid_payload


@pytest.mark.parametrize("legacy", [False, True])
def test_maintenance_schedule_migration_preserves_records_and_is_reversible(db, legacy):
    item, _ = write_opportunity(
        db, data=OpportunityInput.model_validate(valid_payload()),
        request_id="schedule-migration-write", client_name="pytest",
    )
    db.add(CollectionTarget(company_id=item.company_id))
    db.commit()
    path = Path(__file__).parents[1] / "alembic/versions/20261005_0017_add_maintenance_review_schedule.py"
    spec = importlib.util.spec_from_file_location("maintenance_schedule_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with db.get_bind().begin() as connection, Operations.context(MigrationContext.configure(connection)):
        if legacy:
            migration.downgrade()
        before = connection.execute(text("SELECT id, company_id, deadline, source_checked_at FROM opportunities")).all()
        migration.upgrade()
        migration.upgrade()
        assert "date_status_reviewed_at" in {c["name"] for c in inspect(connection).get_columns("opportunities")}
        assert connection.scalar(text("SELECT date_status_reviewed_at FROM opportunities")) is None
        assert connection.scalar(text("SELECT consecutive_failed_checks FROM collection_targets")) == 0
        assert connection.execute(text("SELECT id, company_id, deadline, source_checked_at FROM opportunities")).all() == before
        migration.downgrade()
        assert "consecutive_failed_checks" not in {c["name"] for c in inspect(connection).get_columns("collection_targets")}
        migration.upgrade()
    db.expire_all()
