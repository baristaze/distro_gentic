"""Every column of the platform's own that names an agent session, an agent
step, a spend hold, a spend budget, or an agent workspace says so, as the
engine's own do, and so does every index over one. Each not-null
constraint takes the name its table and column give it. Every row stays,
and the downgrade restores the names before.

Revision ID: 202610121815
Revises: 202610121814
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121815"
down_revision = "202610121814"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121815_columns_take_the_engines_nouns.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121815_columns_take_the_engines_nouns.down.sql")
