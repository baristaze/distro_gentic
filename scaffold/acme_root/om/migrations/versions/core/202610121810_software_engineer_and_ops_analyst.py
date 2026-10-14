"""The engineer kind is the software engineer and the operator kind the ops
analyst: every stored kind id moves in place, on sessions, pins,
connectors' attachments, the matrix's rows, benchmarks, agent
automations' actions, and pin events in the outbox, and the hand-off
tool's new name where sessions, policies, and gates pinned it.

Revision ID: 202610121810
Revises: 202610121809
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121810"
down_revision = "202610121809"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121810_software_engineer_and_ops_analyst.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121810_software_engineer_and_ops_analyst.down.sql")
