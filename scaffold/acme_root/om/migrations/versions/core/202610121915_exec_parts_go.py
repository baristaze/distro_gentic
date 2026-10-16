"""A command's live output is a stream on the shared cache, and its result
holds it whole, so the exec relay's parts table goes.

Revision ID: 202610121915
Revises: 202610121815
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121915"
down_revision = "202610121815"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121915_exec_parts_go.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121915_exec_parts_go.down.sql")
