-- The release before reads the names it wrote. Every row stays.

ALTER TABLE activity.events NO FORCE ROW LEVEL SECURITY;
UPDATE activity.events SET kind = CASE kind
        WHEN 'agent_projects.agent_project.created' THEN 'projects.project.created'
        WHEN 'agent_projects.agent_project.updated' THEN 'projects.project.updated'
        WHEN 'agent_projects.agent_project.deleted' THEN 'projects.project.deleted'
    END
    WHERE kind IN ('agent_projects.agent_project.created', 'agent_projects.agent_project.updated', 'agent_projects.agent_project.deleted');
UPDATE activity.events
    SET payload = jsonb_set(payload, '{kind}', to_jsonb(CASE payload ->> 'kind'
        WHEN 'agent_projects.agent_project.created' THEN 'projects.project.created'
        WHEN 'agent_projects.agent_project.updated' THEN 'projects.project.updated'
        WHEN 'agent_projects.agent_project.deleted' THEN 'projects.project.deleted'
    END))
    WHERE kind = 'outbox.row.failed' AND payload ->> 'kind' IN ('agent_projects.agent_project.created', 'agent_projects.agent_project.updated', 'agent_projects.agent_project.deleted');
ALTER TABLE activity.events FORCE ROW LEVEL SECURITY;

ALTER TABLE activity.validations RENAME COLUMN agent_project TO project;

ALTER TABLE activity.execution_records RENAME COLUMN agent_project TO project;
