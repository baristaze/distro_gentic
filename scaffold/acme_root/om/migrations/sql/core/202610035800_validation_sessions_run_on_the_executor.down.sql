-- A session this release wrote names no lab, so the previous release can
-- read none of them: they go, with the fence lifted for this transaction
-- alone, since the migration login owns the table and FORCE binds the
-- owner. The previous release's columns hold their NOT NULL again.

ALTER TABLE core.validation_sessions NO FORCE ROW LEVEL SECURITY;
DELETE FROM core.validation_sessions WHERE lab_id IS NULL;
ALTER TABLE core.validation_sessions FORCE ROW LEVEL SECURITY;

ALTER TABLE core.validation_sessions
    DROP COLUMN project_id,
    DROP COLUMN head,
    DROP COLUMN base,
    ALTER COLUMN lab_id SET NOT NULL,
    ALTER COLUMN check_version SET NOT NULL,
    ALTER COLUMN parameters SET NOT NULL;
