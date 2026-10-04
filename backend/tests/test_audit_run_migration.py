import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text


@pytest.mark.parametrize("legacy", [False, True])
def test_audit_run_migration_preserves_existing_data_and_is_reversible(db, legacy):
    path = Path(__file__).parents[1] / "alembic/versions/20261004_0016_add_audit_run_id.py"
    spec = importlib.util.spec_from_file_location("audit_run_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with db.get_bind().begin() as connection, Operations.context(MigrationContext.configure(connection)):
        if legacy:
            migration.downgrade()
        connection.execute(text(
            "INSERT INTO audit_logs (action, entity_type, request_id, client_name, success) "
            "VALUES ('verify', 'opportunity', 'legacy-audit-0001', 'test', true)"
        ))
        before = connection.execute(text(
            "SELECT id, action, entity_type, request_id, client_name, success, created_at FROM audit_logs"
        )).all()
        migration.upgrade()
        migration.upgrade()
        assert "run_id" in {column["name"] for column in inspect(connection).get_columns("audit_logs")}
        assert "ix_audit_logs_run_id" in {index["name"] for index in inspect(connection).get_indexes("audit_logs")}
        assert connection.scalar(text("SELECT run_id FROM audit_logs")) is None
        assert connection.execute(text(
            "SELECT id, action, entity_type, request_id, client_name, success, created_at FROM audit_logs"
        )).all() == before
        migration.downgrade()
        assert "run_id" not in {column["name"] for column in inspect(connection).get_columns("audit_logs")}
        migration.upgrade()
        connection.execute(text("UPDATE audit_logs SET run_id = 'new-execution'"))
        assert connection.scalar(text("SELECT run_id FROM audit_logs")) == "new-execution"
