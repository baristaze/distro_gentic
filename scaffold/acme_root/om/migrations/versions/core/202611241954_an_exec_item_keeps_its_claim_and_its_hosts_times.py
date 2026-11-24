"""An exec item keeps when its host's claim took it and the times its host
sent with its result, which the runner measures the relay by.

Revision ID: 202611241954
Revises: 202611211011
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202611241954"
down_revision = "202611211011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(
        DatabaseRole.CORE, "202611241954_an_exec_item_keeps_its_claim_and_its_hosts_times.up.sql"
    )


def downgrade() -> None:
    run_sql(
        DatabaseRole.CORE, "202611241954_an_exec_item_keeps_its_claim_and_its_hosts_times.down.sql"
    )
