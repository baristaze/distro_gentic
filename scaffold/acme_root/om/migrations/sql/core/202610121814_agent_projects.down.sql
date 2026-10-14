-- The release before reads the names it wrote. Every row stays.

ALTER TABLE core.agent_sessions NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_sessions SET tools = (
    SELECT jsonb_agg(to_jsonb(CASE t WHEN 'list_agent_projects' THEN 'list_projects' WHEN 'read_agent_project' THEN 'read_project' ELSE t END) ORDER BY o)
    FROM jsonb_array_elements_text(tools) WITH ORDINALITY AS x (t, o)
)
    WHERE tools ?| ARRAY['list_agent_projects', 'read_agent_project'];
ALTER TABLE core.agent_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE core.tool_policies NO FORCE ROW LEVEL SECURITY;
UPDATE core.tool_policies SET rules = (
    SELECT jsonb_agg(
        CASE WHEN r ->> 'tool' IN ('list_agent_projects', 'read_agent_project')
            THEN jsonb_set(r, '{tool}', to_jsonb(CASE r ->> 'tool' WHEN 'list_agent_projects' THEN 'list_projects' WHEN 'read_agent_project' THEN 'read_project' ELSE r ->> 'tool' END))
            ELSE r
        END
        ORDER BY o
    )
    FROM jsonb_array_elements(rules) WITH ORDINALITY AS x (r, o)
)
    WHERE jsonb_path_exists(rules, '$[*] ? (@.tool == "list_agent_projects" || @.tool == "read_agent_project")');
ALTER TABLE core.tool_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE core.agent_playbooks NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_playbooks SET gates = (
    SELECT jsonb_agg(
        CASE WHEN r ->> 'tool' IN ('list_agent_projects', 'read_agent_project')
            THEN jsonb_set(r, '{tool}', to_jsonb(CASE r ->> 'tool' WHEN 'list_agent_projects' THEN 'list_projects' WHEN 'read_agent_project' THEN 'read_project' ELSE r ->> 'tool' END))
            ELSE r
        END
        ORDER BY o
    )
    FROM jsonb_array_elements(gates) WITH ORDINALITY AS x (r, o)
)
    WHERE jsonb_path_exists(gates, '$[*] ? (@.tool == "list_agent_projects" || @.tool == "read_agent_project")');
ALTER TABLE core.agent_playbooks FORCE ROW LEVEL SECURITY;

ALTER TABLE core.outbox_rows NO FORCE ROW LEVEL SECURITY;
UPDATE core.outbox_rows SET kind = CASE kind
        WHEN 'agent_projects.agent_project.created' THEN 'projects.project.created'
        WHEN 'agent_projects.agent_project.updated' THEN 'projects.project.updated'
        WHEN 'agent_projects.agent_project.deleted' THEN 'projects.project.deleted'
    END
    WHERE kind IN ('agent_projects.agent_project.created', 'agent_projects.agent_project.updated', 'agent_projects.agent_project.deleted');
ALTER TABLE core.outbox_rows FORCE ROW LEVEL SECURITY;

-- What names an agent project inside a stored value moves back: an
-- agent automation's action, a connector's attachments, a retention
-- policy's narrowings, a benchmark trial's hidden runs, and the work and
-- events still waiting in the outbox.

ALTER TABLE core.agent_automations NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_automations
    SET action = (action - 'agent_project_id') || jsonb_build_object('project_id', action -> 'agent_project_id')
    WHERE action ? 'agent_project_id';
ALTER TABLE core.agent_automations FORCE ROW LEVEL SECURITY;

ALTER TABLE core.connectors NO FORCE ROW LEVEL SECURITY;
UPDATE core.connectors SET attachments = (
    SELECT jsonb_agg(
        CASE WHEN e ? 'agent_project_id' THEN (e - 'agent_project_id') || jsonb_build_object('project_id', e -> 'agent_project_id') ELSE e END
        ORDER BY o
    )
    FROM jsonb_array_elements(attachments) WITH ORDINALITY AS x (e, o)
)
    WHERE jsonb_path_exists(attachments, '$[*] ? (exists (@.agent_project_id))');
ALTER TABLE core.connectors FORCE ROW LEVEL SECURITY;

ALTER TABLE core.retention_policies NO FORCE ROW LEVEL SECURITY;
UPDATE core.retention_policies SET agent_projects = (
    SELECT jsonb_agg(
        CASE WHEN e ? 'agent_project_id' THEN (e - 'agent_project_id') || jsonb_build_object('project_id', e -> 'agent_project_id') ELSE e END
        ORDER BY o
    )
    FROM jsonb_array_elements(agent_projects) WITH ORDINALITY AS x (e, o)
)
    WHERE jsonb_path_exists(agent_projects, '$[*] ? (exists (@.agent_project_id))');
ALTER TABLE core.retention_policies FORCE ROW LEVEL SECURITY;

UPDATE core.benchmarks SET trials = (
    SELECT jsonb_agg(
        CASE WHEN jsonb_typeof(t #> '{verdict,hidden}') = 'array' THEN jsonb_set(t, '{verdict,hidden}', (
            SELECT coalesce(jsonb_agg(
                CASE WHEN h ? 'agent_project' THEN (h - 'agent_project') || jsonb_build_object('project', h -> 'agent_project') ELSE h END
                ORDER BY ho
            ), '[]'::jsonb)
            FROM jsonb_array_elements(t #> '{verdict,hidden}') WITH ORDINALITY AS y (h, ho)
        )) ELSE t END
        ORDER BY o
    )
    FROM jsonb_array_elements(trials) WITH ORDINALITY AS x (t, o)
)
    WHERE jsonb_path_exists(trials, '$[*].verdict.hidden[*] ? (exists (@.agent_project))');

ALTER TABLE core.outbox_rows NO FORCE ROW LEVEL SECURITY;
UPDATE core.outbox_rows
    SET payload = (payload - 'agent_project_id') || jsonb_build_object('project_id', payload -> 'agent_project_id')
    WHERE payload ? 'agent_project_id';
ALTER TABLE core.outbox_rows FORCE ROW LEVEL SECURITY;

-- A firing refused for naming no agent project, and a secret an agent
-- project owns, say so by the old name.

ALTER TABLE core.agent_automation_runs NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_automation_runs SET refusal = 'project' WHERE refusal = 'agent_project';
ALTER TABLE core.agent_automation_runs FORCE ROW LEVEL SECURITY;

ALTER TABLE core.secret_declarations NO FORCE ROW LEVEL SECURITY;
UPDATE core.secret_declarations SET owner_kind = 'project' WHERE owner_kind = 'agent_project';
ALTER TABLE core.secret_declarations FORCE ROW LEVEL SECURITY;

ALTER TABLE core.validation_sessions RENAME COLUMN agent_project_id TO project_id;

ALTER INDEX core.uq_validation_policies_org_id_agent_project RENAME TO uq_validation_policies_org_id_project;
ALTER TABLE core.validation_policies RENAME COLUMN agent_project TO project;

ALTER TABLE core.retention_policies RENAME COLUMN agent_projects TO projects;

ALTER INDEX core.uq_egress_allowlists_org_id_agent_project_id RENAME TO uq_egress_allowlists_org_id_project_id;
ALTER TABLE core.egress_allowlists RENAME COLUMN agent_project_id TO project_id;

ALTER TABLE core.agent_session_workspaces RENAME COLUMN agent_project_id TO project_id;

ALTER TABLE core.agent_session_retention RENAME COLUMN agent_project_id TO project_id;

ALTER INDEX core.uq_agent_playbook_pins_org_id_kind_agent_project_id RENAME TO uq_agent_playbook_pins_org_id_kind_project_id;
ALTER TABLE core.agent_playbook_pins RENAME COLUMN agent_project_id TO project_id;

ALTER TABLE core.agent_knowledge_entries RENAME COLUMN agent_project_id TO project_id;

ALTER TABLE core.agent_session_projects RENAME CONSTRAINT pk_agent_session_projects TO pk_session_projects;
ALTER INDEX core.ix_agent_session_projects_org_id RENAME TO ix_session_projects_org_id;
ALTER TABLE core.agent_session_projects RENAME COLUMN agent_project_id TO project_id;
ALTER TABLE core.agent_session_projects RENAME TO session_projects;

ALTER TABLE core.agent_projects RENAME CONSTRAINT pk_agent_projects TO pk_projects;
ALTER INDEX core.ix_agent_projects_org_id RENAME TO ix_projects_org_id;
ALTER TABLE core.agent_projects RENAME TO projects;
