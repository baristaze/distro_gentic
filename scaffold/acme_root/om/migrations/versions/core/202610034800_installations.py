"""The installations a tenant connects, each naming one tenant across every
tenant, and when a person read a notification.

Revision ID: 202610034800
Revises: 202610034700
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610034800"
down_revision = "202610034700"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610034800_installations.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610034800_installations.down.sql")
