"""A knowledge entry belongs to one project of its tenant, or to the whole
tenant, and carries the slug an agent reads it by.

Revision ID: 202610036000
Revises: 202610035900
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610036000"
down_revision = "202610035900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610036000_knowledge_scopes.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610036000_knowledge_scopes.down.sql")
