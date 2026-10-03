-- The sweep settles the ledger's holds no settlement closed, across
-- tenants, reading one slice of their opening times a pass: the index
-- bounds that read, and the ledger's unique index by hold answers whether
-- each is closed.

CREATE INDEX ix_ledger_entries_kind_created_at ON activity.ledger_entries (kind, created_at);
