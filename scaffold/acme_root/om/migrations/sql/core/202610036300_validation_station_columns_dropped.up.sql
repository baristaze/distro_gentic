-- The station's columns leave the table, a release after they left the
-- mapping (ADR 0038), and the columns the model holds turn NOT NULL. A
-- row the release before them wrote names a lab and no project or commit:
-- nothing can fill those, the labs are gone, and this release can read no
-- such row, so it goes. The fence binds the owner and a migration names
-- no tenant, so it is lifted for the one delete, every tenant's, and put
-- back in the migration's transaction. A row this release wrote holds
-- every column it needs, and is kept.

ALTER TABLE core.validation_sessions NO FORCE ROW LEVEL SECURITY;
DELETE FROM core.validation_sessions
    WHERE project_id IS NULL OR head IS NULL OR base IS NULL;
ALTER TABLE core.validation_sessions FORCE ROW LEVEL SECURITY;

ALTER TABLE core.validation_sessions
    DROP COLUMN lab_id,
    DROP COLUMN check_version,
    DROP COLUMN parameters,
    ALTER COLUMN project_id SET NOT NULL,
    ALTER COLUMN head SET NOT NULL,
    ALTER COLUMN base SET NOT NULL;
