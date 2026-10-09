-- Takes the read time and the installations back out: the column, then the
-- fence, then its table.

ALTER TABLE core.notifications DROP COLUMN read_at;
DROP POLICY tenant_fence ON core.installations;
DROP TABLE core.installations;
