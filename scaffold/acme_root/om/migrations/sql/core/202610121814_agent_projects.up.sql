-- A project is an agent project: its two tables, every column that names
-- one, and their keys and indexes take the name. Every row stays.

ALTER TABLE core.projects RENAME TO agent_projects;
ALTER TABLE core.agent_projects RENAME CONSTRAINT pk_projects TO pk_agent_projects;
ALTER INDEX core.ix_projects_org_id RENAME TO ix_agent_projects_org_id;

ALTER TABLE core.session_projects RENAME TO agent_session_projects;
ALTER TABLE core.agent_session_projects RENAME COLUMN project_id TO agent_project_id;
ALTER TABLE core.agent_session_projects RENAME CONSTRAINT pk_session_projects TO pk_agent_session_projects;
ALTER INDEX core.ix_session_projects_org_id RENAME TO ix_agent_session_projects_org_id;

ALTER TABLE core.agent_knowledge_entries RENAME COLUMN project_id TO agent_project_id;

ALTER TABLE core.agent_playbook_pins RENAME COLUMN project_id TO agent_project_id;
ALTER INDEX core.uq_agent_playbook_pins_org_id_kind_project_id RENAME TO uq_agent_playbook_pins_org_id_kind_agent_project_id;

ALTER TABLE core.agent_session_retention RENAME COLUMN project_id TO agent_project_id;

ALTER TABLE core.agent_session_workspaces RENAME COLUMN project_id TO agent_project_id;

ALTER TABLE core.egress_allowlists RENAME COLUMN project_id TO agent_project_id;
ALTER INDEX core.uq_egress_allowlists_org_id_project_id RENAME TO uq_egress_allowlists_org_id_agent_project_id;

ALTER TABLE core.retention_policies RENAME COLUMN projects TO agent_projects;

ALTER TABLE core.validation_policies RENAME COLUMN project TO agent_project;
ALTER INDEX core.uq_validation_policies_org_id_project RENAME TO uq_validation_policies_org_id_agent_project;

ALTER TABLE core.validation_sessions RENAME COLUMN project_id TO agent_project_id;

-- What names an agent project inside a stored value moves in place: an
-- agent automation's action, a connector's attachments, a retention
-- policy's narrowings, a benchmark trial's hidden runs, and the work and
-- events still waiting in the outbox.

ALTER TABLE core.agent_automations NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_automations
    SET action = (action - 'project_id') || jsonb_build_object('agent_project_id', action -> 'project_id')
    WHERE action ? 'project_id';
ALTER TABLE core.agent_automations FORCE ROW LEVEL SECURITY;

ALTER TABLE core.connectors NO FORCE ROW LEVEL SECURITY;
UPDATE core.connectors SET attachments = (
    SELECT jsonb_agg(
        CASE WHEN e ? 'project_id' THEN (e - 'project_id') || jsonb_build_object('agent_project_id', e -> 'project_id') ELSE e END
        ORDER BY o
    )
    FROM jsonb_array_elements(attachments) WITH ORDINALITY AS x (e, o)
)
    WHERE jsonb_path_exists(attachments, '$[*] ? (exists (@.project_id))');
ALTER TABLE core.connectors FORCE ROW LEVEL SECURITY;

ALTER TABLE core.retention_policies NO FORCE ROW LEVEL SECURITY;
UPDATE core.retention_policies SET agent_projects = (
    SELECT jsonb_agg(
        CASE WHEN e ? 'project_id' THEN (e - 'project_id') || jsonb_build_object('agent_project_id', e -> 'project_id') ELSE e END
        ORDER BY o
    )
    FROM jsonb_array_elements(agent_projects) WITH ORDINALITY AS x (e, o)
)
    WHERE jsonb_path_exists(agent_projects, '$[*] ? (exists (@.project_id))');
ALTER TABLE core.retention_policies FORCE ROW LEVEL SECURITY;

UPDATE core.benchmarks SET trials = (
    SELECT jsonb_agg(
        CASE WHEN jsonb_typeof(t #> '{verdict,hidden}') = 'array' THEN jsonb_set(t, '{verdict,hidden}', (
            SELECT coalesce(jsonb_agg(
                CASE WHEN h ? 'project' THEN (h - 'project') || jsonb_build_object('agent_project', h -> 'project') ELSE h END
                ORDER BY ho
            ), '[]'::jsonb)
            FROM jsonb_array_elements(t #> '{verdict,hidden}') WITH ORDINALITY AS y (h, ho)
        )) ELSE t END
        ORDER BY o
    )
    FROM jsonb_array_elements(trials) WITH ORDINALITY AS x (t, o)
)
    WHERE jsonb_path_exists(trials, '$[*].verdict.hidden[*] ? (exists (@.project))');

ALTER TABLE core.outbox_rows NO FORCE ROW LEVEL SECURITY;
UPDATE core.outbox_rows
    SET payload = (payload - 'project_id') || jsonb_build_object('agent_project_id', payload -> 'project_id')
    WHERE payload ? 'project_id';
ALTER TABLE core.outbox_rows FORCE ROW LEVEL SECURITY;

-- A firing refused for naming no agent project, and a secret an agent
-- project owns, say so by the new name.

ALTER TABLE core.agent_automation_runs NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_automation_runs SET refusal = 'agent_project' WHERE refusal = 'project';
ALTER TABLE core.agent_automation_runs FORCE ROW LEVEL SECURITY;

ALTER TABLE core.secret_declarations NO FORCE ROW LEVEL SECURITY;
UPDATE core.secret_declarations SET owner_kind = 'agent_project' WHERE owner_kind = 'project';
ALTER TABLE core.secret_declarations FORCE ROW LEVEL SECURITY;

-- The tools' new names move in place where a session pinned them and
-- where a policy's rule or a gate names one.
ALTER TABLE core.agent_sessions NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_sessions SET tools = (
    SELECT jsonb_agg(to_jsonb(CASE t WHEN 'list_projects' THEN 'list_agent_projects' WHEN 'read_project' THEN 'read_agent_project' ELSE t END) ORDER BY o)
    FROM jsonb_array_elements_text(tools) WITH ORDINALITY AS x (t, o)
)
    WHERE tools ?| ARRAY['list_projects', 'read_project'];
ALTER TABLE core.agent_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE core.tool_policies NO FORCE ROW LEVEL SECURITY;
UPDATE core.tool_policies SET rules = (
    SELECT jsonb_agg(
        CASE WHEN r ->> 'tool' IN ('list_projects', 'read_project')
            THEN jsonb_set(r, '{tool}', to_jsonb(CASE r ->> 'tool' WHEN 'list_projects' THEN 'list_agent_projects' WHEN 'read_project' THEN 'read_agent_project' ELSE r ->> 'tool' END))
            ELSE r
        END
        ORDER BY o
    )
    FROM jsonb_array_elements(rules) WITH ORDINALITY AS x (r, o)
)
    WHERE jsonb_path_exists(rules, '$[*] ? (@.tool == "list_projects" || @.tool == "read_project")');
ALTER TABLE core.tool_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE core.agent_playbooks NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_playbooks SET gates = (
    SELECT jsonb_agg(
        CASE WHEN r ->> 'tool' IN ('list_projects', 'read_project')
            THEN jsonb_set(r, '{tool}', to_jsonb(CASE r ->> 'tool' WHEN 'list_projects' THEN 'list_agent_projects' WHEN 'read_project' THEN 'read_agent_project' ELSE r ->> 'tool' END))
            ELSE r
        END
        ORDER BY o
    )
    FROM jsonb_array_elements(gates) WITH ORDINALITY AS x (r, o)
)
    WHERE jsonb_path_exists(gates, '$[*] ? (@.tool == "list_projects" || @.tool == "read_project")');
ALTER TABLE core.agent_playbooks FORCE ROW LEVEL SECURITY;

-- The kinds of the events they announce move in place.
ALTER TABLE core.outbox_rows NO FORCE ROW LEVEL SECURITY;
UPDATE core.outbox_rows SET kind = CASE kind
        WHEN 'projects.project.created' THEN 'agent_projects.agent_project.created'
        WHEN 'projects.project.updated' THEN 'agent_projects.agent_project.updated'
        WHEN 'projects.project.deleted' THEN 'agent_projects.agent_project.deleted'
    END
    WHERE kind IN ('projects.project.created', 'projects.project.updated', 'projects.project.deleted');
ALTER TABLE core.outbox_rows FORCE ROW LEVEL SECURITY;
