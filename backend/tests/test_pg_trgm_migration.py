import pytest
from sqlalchemy import inspect, text

from app.db import engine


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL migration assertion")
def test_relevance_search_migration_installs_extension_and_indexes():
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')")
        )
        indexes = {
            index["name"] for table in ("companies", "opportunities")
            for index in inspect(connection).get_indexes(table)
        }

    assert {
        "ix_companies_name_trgm",
        "ix_opportunities_event_name_trgm",
        "ix_opportunities_description_trgm",
        "ix_opportunities_requirements_trgm",
    } <= indexes
