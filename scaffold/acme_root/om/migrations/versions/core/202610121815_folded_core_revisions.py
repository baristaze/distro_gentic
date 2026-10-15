"""The platform's own tables of the core role, on the engine's.

Revision ID: 202610121815
Revises: 202610150049
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121815"
down_revision = "202610150049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121815_folded_core_revisions.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121815_folded_core_revisions.down.sql")
