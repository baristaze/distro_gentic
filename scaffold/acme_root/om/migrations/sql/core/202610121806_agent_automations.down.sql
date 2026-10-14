-- The release before reads the names it wrote. Every row stays.

ALTER TABLE core.agent_sessions NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_sessions SET tools = (
    SELECT jsonb_agg(to_jsonb(CASE t WHEN 'list_agent_automations' THEN 'list_automations' WHEN 'read_agent_automation' THEN 'read_automation' ELSE t END) ORDER BY o)
    FROM jsonb_array_elements_text(tools) WITH ORDINALITY AS x (t, o)
)
    WHERE tools ?| ARRAY['list_agent_automations', 'read_agent_automation'];
ALTER TABLE core.agent_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE core.tool_policies NO FORCE ROW LEVEL SECURITY;
UPDATE core.tool_policies SET rules = (
    SELECT jsonb_agg(
        CASE WHEN r ->> 'tool' IN ('list_agent_automations', 'read_agent_automation')
            THEN jsonb_set(r, '{tool}', to_jsonb(CASE r ->> 'tool' WHEN 'list_agent_automations' THEN 'list_automations' WHEN 'read_agent_automation' THEN 'read_automation' ELSE r ->> 'tool' END))
            ELSE r
        END
        ORDER BY o
    )
    FROM jsonb_array_elements(rules) WITH ORDINALITY AS x (r, o)
)
    WHERE jsonb_path_exists(rules, '$[*] ? (@.tool == "list_agent_automations" || @.tool == "read_agent_automation")');
ALTER TABLE core.tool_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE core.playbooks NO FORCE ROW LEVEL SECURITY;
UPDATE core.playbooks SET gates = (
    SELECT jsonb_agg(
        CASE WHEN r ->> 'tool' IN ('list_agent_automations', 'read_agent_automation')
            THEN jsonb_set(r, '{tool}', to_jsonb(CASE r ->> 'tool' WHEN 'list_agent_automations' THEN 'list_automations' WHEN 'read_agent_automation' THEN 'read_automation' ELSE r ->> 'tool' END))
            ELSE r
        END
        ORDER BY o
    )
    FROM jsonb_array_elements(gates) WITH ORDINALITY AS x (r, o)
)
    WHERE jsonb_path_exists(gates, '$[*] ? (@.tool == "list_agent_automations" || @.tool == "read_agent_automation")');
ALTER TABLE core.playbooks FORCE ROW LEVEL SECURITY;

ALTER TABLE core.outbox_rows NO FORCE ROW LEVEL SECURITY;
UPDATE core.outbox_rows SET kind = CASE kind
        WHEN 'agent_automations.agent_automation.created' THEN 'automations.automation.created'
        WHEN 'agent_automations.agent_automation.updated' THEN 'automations.automation.updated'
        WHEN 'agent_automations.principal.granted' THEN 'automations.principal.granted'
    END
    WHERE kind IN ('agent_automations.agent_automation.created', 'agent_automations.agent_automation.updated', 'agent_automations.principal.granted');
ALTER TABLE core.outbox_rows FORCE ROW LEVEL SECURITY;

ALTER TABLE core.agent_automations NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_automations SET runs_as = 'automation_principal'
    WHERE runs_as = 'agent_automation_principal';
ALTER TABLE core.agent_automations FORCE ROW LEVEL SECURITY;

ALTER TABLE core.agent_automation_principals RENAME CONSTRAINT pk_agent_automation_principals TO pk_automation_principals;
ALTER INDEX core.uq_agent_automation_principals_org_id RENAME TO uq_automation_principals_org_id;
ALTER TABLE core.agent_automation_principals RENAME TO automation_principals;

ALTER TABLE core.agent_automation_runs RENAME CONSTRAINT pk_agent_automation_runs TO pk_automation_runs;
ALTER INDEX core.ix_agent_automation_runs_org_id_agent_automation_id_created_at RENAME TO ix_automation_runs_org_id_automation_id_created_at;
ALTER INDEX core.ix_agent_automation_runs_org_id_automation_id_status_created_at RENAME TO ix_automation_runs_org_id_automation_id_status_created_at;
ALTER INDEX core.ix_agent_automation_runs_org_id_session_id RENAME TO ix_automation_runs_org_id_session_id;
ALTER TABLE core.agent_automation_runs RENAME COLUMN agent_automation_id TO automation_id;
ALTER TABLE core.agent_automation_runs RENAME TO automation_runs;

ALTER TABLE core.agent_automations RENAME CONSTRAINT pk_agent_automations TO pk_automations;
ALTER INDEX core.ix_agent_automations_org_id RENAME TO ix_automations_org_id;
ALTER TABLE core.agent_automations RENAME TO automations;
