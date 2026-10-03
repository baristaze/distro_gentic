-- The sweep settles the holds no settlement closed, across tenants, reading
-- one slice of their opening times a pass: the index bounds that read, and
-- the settlements' unique index answers whether each is closed.

CREATE INDEX ix_budget_holds_created_at ON activity.budget_holds (created_at);
