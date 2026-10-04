-- A job's hold names the job's deadline, which it lives to: the sweep takes
-- it up past that deadline, and every other hold past its opening time. A
-- hold with no deadline is a model call's. The previous release writes
-- only those, without the column, for the minutes of the roll, so the
-- column is nullable and no row is backfilled. The index holds the
-- deadlines alone, which bound the sweep's read of the jobs' holds.

ALTER TABLE activity.ledger_entries ADD COLUMN deadline timestamptz;
CREATE INDEX ix_ledger_entries_kind_deadline ON activity.ledger_entries (kind, deadline) WHERE deadline IS NOT NULL;
