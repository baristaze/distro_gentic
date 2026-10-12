"""A tenant connects its servers as toolsets: each connector, the tools of
it a person reviewed, and the kinds it is attached to; and what each
session pinned of them.

Revision ID: 202610112133
Revises: 202610112033
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610112133"
down_revision = "202610112033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610112133_a_tenant_connects_its_servers_as_toolsets.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610112133_a_tenant_connects_its_servers_as_toolsets.down.sql")
