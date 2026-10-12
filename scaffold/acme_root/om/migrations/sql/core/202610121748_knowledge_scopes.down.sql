-- The previous release reads every reviewed entry as its whole tenant's,
-- so an entry of one project would reach every other project's sessions.
-- Each one goes back to waiting for a person's review instead: its words
-- are kept, and no session reads it until a person keeps it again. The
-- fence is lifted for this transaction alone, since the migration login
-- owns the table and FORCE binds the owner.

ALTER TABLE core.knowledge_entries NO FORCE ROW LEVEL SECURITY;
UPDATE core.knowledge_entries
SET status = 'suggested', reviewed_by = NULL, version = version + 1
WHERE project_id IS NOT NULL AND status = 'reviewed';
ALTER TABLE core.knowledge_entries FORCE ROW LEVEL SECURITY;

DROP INDEX core.ix_knowledge_entries_org_id_slug;
ALTER TABLE core.knowledge_entries
    DROP COLUMN slug,
    DROP COLUMN project_id;
