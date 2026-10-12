"""A lever carries its findings and a recall its version: the findings the
lever checks read in each playbook version and knowledge entry, and the
entry versions each session recalled.

Revision ID: 202610121801
Revises: 202610121800
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121801"
down_revision = "202610121800"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(
        DatabaseRole.CORE,
        "202610121801_a_lever_carries_its_findings_and_a_recall_its_version.up.sql",
    )


def downgrade() -> None:
    run_sql(
        DatabaseRole.CORE,
        "202610121801_a_lever_carries_its_findings_and_a_recall_its_version.down.sql",
    )
