"""The cloud pool keeps warm VMs hibernated beside its running ones: a
VM's row says whether it was started to sleep, and since when it sleeps,
and the pool's limits say how many sleep.

Revision ID: 202611242030
Revises: 202611211011
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202611242030"
down_revision = "202611211011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202611242030_the_cloud_pool_keeps_vms_hibernated.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202611242030_the_cloud_pool_keeps_vms_hibernated.down.sql")
