"""A tenant's host pools, enrollment tokens, hosts and their credentials, and
the placement of its sessions, each with its fence.

Revision ID: 202610121734
Revises: 202610121733
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121734"
down_revision = "202610121733"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121734_hosts.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121734_hosts.down.sql")
