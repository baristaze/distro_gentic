"""A project is an agent project: its tables, every column that names one,
and their keys and indexes take the name; what names one inside a stored
value, a refusal, a secret's owner kind, the tools' names, and the kinds
of its events move in place. Every row stays, and the downgrade restores
both.

Revision ID: 202610121814
Revises: 202610121813
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121814"
down_revision = "202610121813"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121814_agent_projects.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121814_agent_projects.down.sql")
