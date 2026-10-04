-- Takes a job's hold's deadline and its index back.

DROP INDEX activity.ix_ledger_entries_kind_deadline;
ALTER TABLE activity.ledger_entries DROP COLUMN deadline;
