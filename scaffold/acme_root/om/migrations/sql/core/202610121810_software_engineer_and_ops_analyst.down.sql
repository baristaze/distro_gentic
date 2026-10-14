-- The release before reads the names it wrote. Every row stays.

ALTER TABLE core.agent_sessions NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_sessions SET tools = (
    SELECT jsonb_agg(to_jsonb(CASE t WHEN 'hand_off_to_software_engineer' THEN 'hand_off_to_engineer' ELSE t END) ORDER BY o)
    FROM jsonb_array_elements_text(tools) WITH ORDINALITY AS x (t, o)
)
    WHERE tools ?| ARRAY['hand_off_to_software_engineer'];
ALTER TABLE core.agent_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE core.tool_policies NO FORCE ROW LEVEL SECURITY;
UPDATE core.tool_policies SET rules = (
    SELECT jsonb_agg(
        CASE WHEN r ->> 'tool' IN ('hand_off_to_software_engineer')
            THEN jsonb_set(r, '{tool}', to_jsonb(CASE r ->> 'tool' WHEN 'hand_off_to_software_engineer' THEN 'hand_off_to_engineer' ELSE r ->> 'tool' END))
            ELSE r
        END
        ORDER BY o
    )
    FROM jsonb_array_elements(rules) WITH ORDINALITY AS x (r, o)
)
    WHERE jsonb_path_exists(rules, '$[*] ? (@.tool == "hand_off_to_software_engineer")');
ALTER TABLE core.tool_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE core.agent_playbooks NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_playbooks SET gates = (
    SELECT jsonb_agg(
        CASE WHEN r ->> 'tool' IN ('hand_off_to_software_engineer')
            THEN jsonb_set(r, '{tool}', to_jsonb(CASE r ->> 'tool' WHEN 'hand_off_to_software_engineer' THEN 'hand_off_to_engineer' ELSE r ->> 'tool' END))
            ELSE r
        END
        ORDER BY o
    )
    FROM jsonb_array_elements(gates) WITH ORDINALITY AS x (r, o)
)
    WHERE jsonb_path_exists(gates, '$[*] ? (@.tool == "hand_off_to_software_engineer")');
ALTER TABLE core.agent_playbooks FORCE ROW LEVEL SECURITY;

ALTER TABLE core.agent_sessions NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_sessions SET kind = CASE kind WHEN 'software_engineer' THEN 'engineer' WHEN 'ops_analyst' THEN 'operator' END WHERE kind IN ('software_engineer', 'ops_analyst');
ALTER TABLE core.agent_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE core.agent_playbook_pins NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_playbook_pins SET kind = CASE kind WHEN 'software_engineer' THEN 'engineer' WHEN 'ops_analyst' THEN 'operator' END WHERE kind IN ('software_engineer', 'ops_analyst');
ALTER TABLE core.agent_playbook_pins FORCE ROW LEVEL SECURITY;
ALTER TABLE core.connectors NO FORCE ROW LEVEL SECURITY;
UPDATE core.connectors SET attachments = (
    SELECT jsonb_agg(
        CASE WHEN a ->> 'kind' IN ('software_engineer', 'ops_analyst')
            THEN jsonb_set(a, '{kind}', to_jsonb(CASE a ->> 'kind' WHEN 'software_engineer' THEN 'engineer' WHEN 'ops_analyst' THEN 'operator' END))
            ELSE a END ORDER BY o)
    FROM jsonb_array_elements(attachments) WITH ORDINALITY AS x (a, o)
)
    WHERE jsonb_path_exists(attachments, '$[*] ? (@.kind == "software_engineer" || @.kind == "ops_analyst")');
ALTER TABLE core.connectors FORCE ROW LEVEL SECURITY;
UPDATE core.matrix_versions SET rows = (
    SELECT jsonb_agg(
        CASE WHEN r #>> '{key,kind}' IN ('software_engineer', 'ops_analyst')
            THEN jsonb_set(r, '{key,kind}', to_jsonb(CASE r #>> '{key,kind}' WHEN 'software_engineer' THEN 'engineer' WHEN 'ops_analyst' THEN 'operator' END))
            ELSE r END ORDER BY o)
    FROM jsonb_array_elements(rows) WITH ORDINALITY AS x (r, o)
)
    WHERE jsonb_path_exists(rows, '$[*] ? (@.key.kind == "software_engineer" || @.key.kind == "ops_analyst")');
UPDATE core.benchmarks SET candidate = jsonb_set(candidate, '{kind}', to_jsonb(CASE candidate ->> 'kind' WHEN 'software_engineer' THEN 'engineer' WHEN 'ops_analyst' THEN 'operator' END)) WHERE candidate ->> 'kind' IN ('software_engineer', 'ops_analyst');
UPDATE core.benchmarks SET baseline = jsonb_set(baseline, '{kind}', to_jsonb(CASE baseline ->> 'kind' WHEN 'software_engineer' THEN 'engineer' WHEN 'ops_analyst' THEN 'operator' END)) WHERE baseline ->> 'kind' IN ('software_engineer', 'ops_analyst');
ALTER TABLE core.agent_automations NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_automations SET action = jsonb_set(action, '{agent_kind}', to_jsonb(CASE action ->> 'agent_kind' WHEN 'software_engineer' THEN 'engineer' WHEN 'ops_analyst' THEN 'operator' END)) WHERE action ->> 'agent_kind' IN ('software_engineer', 'ops_analyst');
ALTER TABLE core.agent_automations FORCE ROW LEVEL SECURITY;
ALTER TABLE core.outbox_rows NO FORCE ROW LEVEL SECURITY;
UPDATE core.outbox_rows SET payload = jsonb_set(payload, '{kind}', to_jsonb(CASE payload ->> 'kind' WHEN 'software_engineer' THEN 'engineer' WHEN 'ops_analyst' THEN 'operator' END)) WHERE kind IN ('agent_playbooks.pin.updated', 'agent_playbooks.pin.deleted') AND payload ->> 'kind' IN ('software_engineer', 'ops_analyst');
ALTER TABLE core.outbox_rows FORCE ROW LEVEL SECURITY;
