-- The release before reads the key it wrote. Every work item stays.

ALTER TABLE queue.work_items NO FORCE ROW LEVEL SECURITY;
UPDATE queue.work_items
    SET payload = (payload - 'agent_project_id') || jsonb_build_object('project_id', payload -> 'agent_project_id')
    WHERE payload ? 'agent_project_id';
ALTER TABLE queue.work_items FORCE ROW LEVEL SECURITY;
