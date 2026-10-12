-- The previous release knows hosts alone, so the claimants of a product's
-- kind go, with their credentials and the tokens that enroll them. The
-- fence is lifted for this transaction alone, since the migration login
-- owns the tables and FORCE binds the owner.

ALTER TABLE core.host_credentials NO FORCE ROW LEVEL SECURITY;
ALTER TABLE core.hosts NO FORCE ROW LEVEL SECURITY;
ALTER TABLE core.host_enrollment_tokens NO FORCE ROW LEVEL SECURITY;
DELETE FROM core.host_credentials AS c
    USING core.hosts AS h
    WHERE c.org_id = h.org_id AND c.host_id = h.id AND h.kind <> 'host';
DELETE FROM core.hosts WHERE kind <> 'host';
DELETE FROM core.host_enrollment_tokens WHERE kind <> 'host';
ALTER TABLE core.host_credentials FORCE ROW LEVEL SECURITY;
ALTER TABLE core.hosts FORCE ROW LEVEL SECURITY;
ALTER TABLE core.host_enrollment_tokens FORCE ROW LEVEL SECURITY;

ALTER TABLE core.hosts ALTER COLUMN exec_version SET NOT NULL;
ALTER TABLE core.hosts ALTER COLUMN advertisement SET NOT NULL;
ALTER TABLE core.hosts DROP COLUMN kind;
ALTER TABLE core.host_enrollment_tokens DROP COLUMN kind;
