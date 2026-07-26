"""Initial MVP schema and fixed masters."""

from alembic import op
from app import models  # noqa: F401
from app.db import Base
from app.master_data import seed_masters

revision = "20260726_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    seed_masters(bind)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
