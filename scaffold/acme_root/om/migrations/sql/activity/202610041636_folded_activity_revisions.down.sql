-- The platform's own tables of the activity role go, grants first, and
-- the role is the engine's.

REVOKE SELECT, DELETE ON activity.execution_records FROM acme_purge;
REVOKE SELECT, DELETE ON activity.inferences FROM acme_purge;
REVOKE SELECT, DELETE ON activity.validations FROM acme_purge;
DROP INDEX activity.ix_spend_budget_holds_created_at;
DROP TABLE activity.validations;
DROP TABLE activity.spend_ledger_entries;
DROP TABLE activity.spend_ledger_counts;
DROP TABLE activity.inferences;
DROP TABLE activity.execution_records;
