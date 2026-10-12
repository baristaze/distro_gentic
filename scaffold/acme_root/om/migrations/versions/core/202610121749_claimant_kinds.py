"""An enrollment token names the claimant kind it enrolls, and an enrolled
claimant its kind: a host, or a product's. What a host advertised and the
version it reads are a host's alone.

Revision ID: 202610121749
Revises: 202610121748
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121749"
down_revision = "202610121748"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121749_claimant_kinds.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121749_claimant_kinds.down.sql")
