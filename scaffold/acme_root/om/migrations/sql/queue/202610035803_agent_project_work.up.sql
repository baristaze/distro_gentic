-- The work a session sends to a host names the agent project it is for:
-- the key moves in place in every work item still held.

ALTER TABLE queue.work_items NO FORCE ROW LEVEL SECURITY;
UPDATE queue.work_items
    SET payload = (payload - 'project_id') || jsonb_build_object('agent_project_id', payload -> 'project_id')
    WHERE payload ? 'project_id';
ALTER TABLE queue.work_items FORCE ROW LEVEL SECURITY;
