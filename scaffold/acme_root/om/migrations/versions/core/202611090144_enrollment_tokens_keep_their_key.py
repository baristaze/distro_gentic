"""An enrollment token keeps the API key its issuer issued it on, so it
enrolls no higher than the key, and only while the key holds.

Revision ID: 202611090144
Revises: 202610121915
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202611090144"
down_revision = "202610121915"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202611090144_enrollment_tokens_keep_their_key.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202611090144_enrollment_tokens_keep_their_key.down.sql")
