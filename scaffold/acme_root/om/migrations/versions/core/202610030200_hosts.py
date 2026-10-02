"""A tenant's host pools, enrollment tokens, hosts and their credentials, and
the placement of its sessions, each with its fence.

Revision ID: 202610030200
Revises: 202610030100
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610030200"
down_revision = "202610030100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610030200_hosts.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610030200_hosts.down.sql")
