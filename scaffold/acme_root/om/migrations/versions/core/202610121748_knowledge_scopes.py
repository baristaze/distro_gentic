"""A knowledge entry belongs to one project of its tenant, or to the whole
tenant, and carries the slug an agent reads it by.

Revision ID: 202610121748
Revises: 202610121747
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121748"
down_revision = "202610121747"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121748_knowledge_scopes.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121748_knowledge_scopes.down.sql")
