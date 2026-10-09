"""The station's columns leave the validation sessions, a release after
they left the mapping, and the columns the model holds turn not null; a
row the release before them wrote, which names no project, goes.

Revision ID: 202610091930
Revises: 202610091929
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610091930"
down_revision = "202610091929"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091930_validation_station_columns_dropped.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091930_validation_station_columns_dropped.down.sql")
