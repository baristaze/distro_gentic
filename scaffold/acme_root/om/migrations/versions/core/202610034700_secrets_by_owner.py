"""A secret's declaration keyed by its owner too, so each project declares
its own secret of a name.

Revision ID: 202610034700
Revises: 202610034500
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610034700"
down_revision = "202610034500"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610034700_secrets_by_owner.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610034700_secrets_by_owner.down.sql")
