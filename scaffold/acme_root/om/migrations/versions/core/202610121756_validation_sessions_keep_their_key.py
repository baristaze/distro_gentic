"""A validation session keeps the API key its starter started it on, so
its run acts no higher than the key.

Revision ID: 202610121756
Revises: 202610121755
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121756"
down_revision = "202610121755"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121756_validation_sessions_keep_their_key.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121756_validation_sessions_keep_their_key.down.sql")
