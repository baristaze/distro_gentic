-- A run and a validation name the agent project whose key they ran for.
-- Every row stays.

ALTER TABLE activity.execution_records RENAME COLUMN project TO agent_project;

ALTER TABLE activity.validations RENAME COLUMN project TO agent_project;

-- The kinds of the events they announce move in place.
ALTER TABLE activity.change_events NO FORCE ROW LEVEL SECURITY;
UPDATE activity.change_events SET kind = CASE kind
        WHEN 'projects.project.created' THEN 'agent_projects.agent_project.created'
        WHEN 'projects.project.updated' THEN 'agent_projects.agent_project.updated'
        WHEN 'projects.project.deleted' THEN 'agent_projects.agent_project.deleted'
    END
    WHERE kind IN ('projects.project.created', 'projects.project.updated', 'projects.project.deleted');
UPDATE activity.change_events
    SET payload = jsonb_set(payload, '{kind}', to_jsonb(CASE payload ->> 'kind'
        WHEN 'projects.project.created' THEN 'agent_projects.agent_project.created'
        WHEN 'projects.project.updated' THEN 'agent_projects.agent_project.updated'
        WHEN 'projects.project.deleted' THEN 'agent_projects.agent_project.deleted'
    END))
    WHERE kind = 'outbox.row.failed' AND payload ->> 'kind' IN ('projects.project.created', 'projects.project.updated', 'projects.project.deleted');
ALTER TABLE activity.change_events FORCE ROW LEVEL SECURITY;
