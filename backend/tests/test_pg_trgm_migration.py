import pytest
from sqlalchemy import inspect, text

from app.db import engine


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL migration assertion")
def test_relevance_search_migration_installs_extension_and_indexes():
    with engine.connect() as connection:
        assert inspect(connection).has_table("company_request_records")
        assert connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')")
        )
        indexes = {
            index["name"] for table in ("companies", "company_aliases", "opportunities")
            for index in inspect(connection).get_indexes(table)
        }

    assert {
        "ix_companies_name_trgm",
        "ix_opportunities_event_name_trgm",
        "ix_opportunities_description_trgm",
        "ix_opportunities_requirements_trgm",
        "ix_companies_normalized_name_trgm",
        "ix_company_aliases_alias_trgm",
        "ix_company_aliases_normalized_alias_trgm",
    } <= indexes
