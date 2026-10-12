"""A playbook is pinned to a kind as its manual: the versions a tenant
pinned to its kinds, for the tenant or one project, and which invocation
of a session is the manual it was made with.

Revision ID: 202610120057
Revises: 202610112033
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610120057"
down_revision = "202610112033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610120057_a_playbook_is_pinned_to_a_kind_as_its_manual.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610120057_a_playbook_is_pinned_to_a_kind_as_its_manual.down.sql")
