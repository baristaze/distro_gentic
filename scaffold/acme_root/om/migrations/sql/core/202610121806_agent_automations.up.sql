-- An automation is an agent automation: its three tables, their columns,
-- and their indexes take the name, and every row stays.

ALTER TABLE core.automations RENAME TO agent_automations;
ALTER TABLE core.agent_automations RENAME CONSTRAINT pk_automations TO pk_agent_automations;
ALTER INDEX core.ix_automations_org_id RENAME TO ix_agent_automations_org_id;

ALTER TABLE core.automation_runs RENAME TO agent_automation_runs;
ALTER TABLE core.agent_automation_runs RENAME COLUMN automation_id TO agent_automation_id;
ALTER TABLE core.agent_automation_runs RENAME CONSTRAINT pk_automation_runs TO pk_agent_automation_runs;
ALTER INDEX core.ix_automation_runs_org_id_automation_id_created_at RENAME TO ix_agent_automation_runs_org_id_agent_automation_id_created_at;
ALTER INDEX core.ix_automation_runs_org_id_automation_id_status_created_at RENAME TO ix_agent_automation_runs_org_id_automation_id_status_created_at;
ALTER INDEX core.ix_automation_runs_org_id_session_id RENAME TO ix_agent_automation_runs_org_id_session_id;

ALTER TABLE core.automation_principals RENAME TO agent_automation_principals;
ALTER TABLE core.agent_automation_principals RENAME CONSTRAINT pk_automation_principals TO pk_agent_automation_principals;
ALTER INDEX core.uq_automation_principals_org_id RENAME TO uq_agent_automation_principals_org_id;

-- One that runs as the tenant's principal names it by its new name.
ALTER TABLE core.agent_automations NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_automations SET runs_as = 'agent_automation_principal'
    WHERE runs_as = 'automation_principal';
ALTER TABLE core.agent_automations FORCE ROW LEVEL SECURITY;

-- The tools' new names move in place where a session pinned them and
-- where a policy's rule or a gate names one.
ALTER TABLE core.agent_sessions NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_sessions SET tools = (
    SELECT jsonb_agg(to_jsonb(CASE t WHEN 'list_automations' THEN 'list_agent_automations' WHEN 'read_automation' THEN 'read_agent_automation' ELSE t END) ORDER BY o)
    FROM jsonb_array_elements_text(tools) WITH ORDINALITY AS x (t, o)
)
    WHERE tools ?| ARRAY['list_automations', 'read_automation'];
ALTER TABLE core.agent_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE core.tool_policies NO FORCE ROW LEVEL SECURITY;
UPDATE core.tool_policies SET rules = (
    SELECT jsonb_agg(
        CASE WHEN r ->> 'tool' IN ('list_automations', 'read_automation')
            THEN jsonb_set(r, '{tool}', to_jsonb(CASE r ->> 'tool' WHEN 'list_automations' THEN 'list_agent_automations' WHEN 'read_automation' THEN 'read_agent_automation' ELSE r ->> 'tool' END))
            ELSE r
        END
        ORDER BY o
    )
    FROM jsonb_array_elements(rules) WITH ORDINALITY AS x (r, o)
)
    WHERE jsonb_path_exists(rules, '$[*] ? (@.tool == "list_automations" || @.tool == "read_automation")');
ALTER TABLE core.tool_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE core.playbooks NO FORCE ROW LEVEL SECURITY;
UPDATE core.playbooks SET gates = (
    SELECT jsonb_agg(
        CASE WHEN r ->> 'tool' IN ('list_automations', 'read_automation')
            THEN jsonb_set(r, '{tool}', to_jsonb(CASE r ->> 'tool' WHEN 'list_automations' THEN 'list_agent_automations' WHEN 'read_automation' THEN 'read_agent_automation' ELSE r ->> 'tool' END))
            ELSE r
        END
        ORDER BY o
    )
    FROM jsonb_array_elements(gates) WITH ORDINALITY AS x (r, o)
)
    WHERE jsonb_path_exists(gates, '$[*] ? (@.tool == "list_automations" || @.tool == "read_automation")');
ALTER TABLE core.playbooks FORCE ROW LEVEL SECURITY;

-- The kinds of the events they announce move in place.
ALTER TABLE core.outbox_rows NO FORCE ROW LEVEL SECURITY;
UPDATE core.outbox_rows SET kind = CASE kind
        WHEN 'automations.automation.created' THEN 'agent_automations.agent_automation.created'
        WHEN 'automations.automation.updated' THEN 'agent_automations.agent_automation.updated'
        WHEN 'automations.principal.granted' THEN 'agent_automations.principal.granted'
    END
    WHERE kind IN ('automations.automation.created', 'automations.automation.updated', 'automations.principal.granted');
ALTER TABLE core.outbox_rows FORCE ROW LEVEL SECURITY;
