"""The cloud pool keeps no disk of any VM: a session's workspace files are
archived in the snapshots bucket, and the pool records each session that
keeps archives, so its sweep removes them once the session is idle. The
erasures of disks it owed, and the flag that named a disk among a
session's snapshots, go.

Revision ID: 202611211011
Revises: 202611210452
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202611211011"
down_revision = "202611210452"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202611211011_the_cloud_pool_keeps_archives_not_disks.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202611211011_the_cloud_pool_keeps_archives_not_disks.down.sql")
