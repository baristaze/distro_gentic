-- Takes the ledger back out: the fences, then the tables.

DROP POLICY tenant_fence ON activity.ledger_entries;
DROP POLICY tenant_fence ON activity.ledger_counts;
DROP TABLE activity.ledger_entries;
DROP TABLE activity.ledger_counts;
