"""The runs, the validations, and the hypotheses and findings, each with
its fence, kept to SELECT and INSERT for the serving logins and taken with
their session or their tenant by the purge login.

Revision ID: 202610030801
Revises: 202610021301
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610030801"
down_revision = "202610021301"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610030801_execution_records.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610030801_execution_records.down.sql")
