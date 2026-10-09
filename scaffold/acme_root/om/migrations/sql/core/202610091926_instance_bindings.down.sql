-- The previous release reads an instance's binding as a session's, so the
-- instances' bindings go, with the fence lifted for this transaction alone,
-- since the migration login owns the table and FORCE binds the owner. Each
-- instance lives for one run, and no run of that release reaches it.

ALTER TABLE core.workspace_bindings NO FORCE ROW LEVEL SECURITY;
DELETE FROM core.workspace_bindings WHERE instance_of IS NOT NULL;
ALTER TABLE core.workspace_bindings FORCE ROW LEVEL SECURITY;

ALTER TABLE core.workspace_bindings DROP COLUMN instance_of;
