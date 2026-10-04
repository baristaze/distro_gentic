-- The previous release knows the platform's two actions alone, and reads
-- an action of any other kind as malformed, so the automations of a
-- product's kind go, with their runs. The fence is lifted for this
-- transaction alone, since the migration login owns the tables and FORCE
-- binds the owner.

ALTER TABLE core.automation_runs NO FORCE ROW LEVEL SECURITY;
ALTER TABLE core.automations NO FORCE ROW LEVEL SECURITY;
DELETE FROM core.automation_runs AS r
    USING core.automations AS a
    WHERE r.org_id = a.org_id AND r.automation_id = a.id
    AND a.action ->> 'kind' NOT IN ('start_session', 'message_session');
DELETE FROM core.automations
    WHERE action ->> 'kind' NOT IN ('start_session', 'message_session');
ALTER TABLE core.automation_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE core.automations FORCE ROW LEVEL SECURITY;

ALTER TABLE core.automation_runs DROP COLUMN outcome;
ALTER TABLE core.automation_runs DROP COLUMN work_id;
