"""The cloud pool's limits, which its operators write and each claim reads:
the pool's own, a row per version, and a tenant's own maximum.

Revision ID: 202611210452
Revises: 202611090144
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202611210452"
down_revision = "202611090144"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202611210452_the_cloud_pools_limits.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202611210452_the_cloud_pools_limits.down.sql")
