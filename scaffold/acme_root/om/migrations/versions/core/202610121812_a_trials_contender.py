"""A benchmark's trial names the contender it ran for, the candidate or the
baseline: the key moves in place in every trial.

Revision ID: 202610121812
Revises: 202610121811
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121812"
down_revision = "202610121811"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121812_a_trials_contender.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121812_a_trials_contender.down.sql")
