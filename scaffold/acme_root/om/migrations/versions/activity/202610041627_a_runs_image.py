"""An execution record names the image it ran on, its run image: the
column takes the name, and every value stays.

Revision ID: 202610041627
Revises: 202610041626
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610041627"
down_revision = "202610041626"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041627_a_runs_image.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041627_a_runs_image.down.sql")
