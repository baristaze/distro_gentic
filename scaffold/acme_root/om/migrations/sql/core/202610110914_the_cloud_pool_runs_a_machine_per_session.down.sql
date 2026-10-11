-- Takes the cloud pool's machines back out. Each session's pool of one goes
-- with its hosts and their credentials, so none becomes a tenant's pool, and
-- so do the records of the snapshots its machines' store kept, which nothing
-- reads without the column that says where they live. The fence is lifted
-- for this transaction alone, since the migration login owns the tables and
-- FORCE binds the owner.

DROP TABLE core.pool_machines;

ALTER TABLE core.workspace_snapshots NO FORCE ROW LEVEL SECURITY;
ALTER TABLE core.host_credentials NO FORCE ROW LEVEL SECURITY;
ALTER TABLE core.hosts NO FORCE ROW LEVEL SECURITY;
ALTER TABLE core.host_pools NO FORCE ROW LEVEL SECURITY;
DELETE FROM core.workspace_snapshots WHERE machine;
DELETE FROM core.host_credentials AS c
    USING core.hosts AS h
    WHERE c.org_id = h.org_id AND c.host_id = h.id AND h.session_id IS NOT NULL;
DELETE FROM core.hosts WHERE session_id IS NOT NULL;
DELETE FROM core.host_pools WHERE session_id IS NOT NULL;
ALTER TABLE core.workspace_snapshots FORCE ROW LEVEL SECURITY;
ALTER TABLE core.host_credentials FORCE ROW LEVEL SECURITY;
ALTER TABLE core.hosts FORCE ROW LEVEL SECURITY;
ALTER TABLE core.host_pools FORCE ROW LEVEL SECURITY;

ALTER TABLE core.workspace_snapshots DROP COLUMN machine;
ALTER TABLE core.hosts DROP COLUMN session_id;
ALTER TABLE core.host_pools DROP COLUMN session_id;
