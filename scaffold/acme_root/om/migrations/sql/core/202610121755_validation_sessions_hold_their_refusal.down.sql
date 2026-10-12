-- The previous release knows no refused session and reads none: each one
-- goes back to queued, as that release left it, and is kept; its reason
-- goes with the column. The fence binds the owner and a migration names no
-- tenant, so it is lifted for the one update, every tenant's, and put back
-- in the migration's transaction.

ALTER TABLE core.validation_sessions NO FORCE ROW LEVEL SECURITY;
UPDATE core.validation_sessions SET status = 'queued' WHERE status = 'refused';
ALTER TABLE core.validation_sessions FORCE ROW LEVEL SECURITY;

ALTER TABLE core.validation_sessions DROP COLUMN refusal;
