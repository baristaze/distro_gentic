"""The rows of intake, automations, playbooks, and knowledge, each with its
fence: account links and work bindings, automations and their runs,
playbook versions and their invocations, and knowledge entries.

Revision ID: 202610032000
Revises: 202610030900
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610032000"
down_revision = "202610030900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610032000_intake.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610032000_intake.down.sql")
