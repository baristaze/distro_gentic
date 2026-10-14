-- The engineer kind is the software engineer and the operator kind the
-- ops analyst: every stored kind id moves in place.

ALTER TABLE core.agent_sessions NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_sessions SET kind = CASE kind WHEN 'engineer' THEN 'software_engineer' WHEN 'operator' THEN 'ops_analyst' END WHERE kind IN ('engineer', 'operator');
ALTER TABLE core.agent_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE core.agent_playbook_pins NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_playbook_pins SET kind = CASE kind WHEN 'engineer' THEN 'software_engineer' WHEN 'operator' THEN 'ops_analyst' END WHERE kind IN ('engineer', 'operator');
ALTER TABLE core.agent_playbook_pins FORCE ROW LEVEL SECURITY;
ALTER TABLE core.connectors NO FORCE ROW LEVEL SECURITY;
UPDATE core.connectors SET attachments = (
    SELECT jsonb_agg(
        CASE WHEN a ->> 'kind' IN ('engineer', 'operator')
            THEN jsonb_set(a, '{kind}', to_jsonb(CASE a ->> 'kind' WHEN 'engineer' THEN 'software_engineer' WHEN 'operator' THEN 'ops_analyst' END))
            ELSE a END ORDER BY o)
    FROM jsonb_array_elements(attachments) WITH ORDINALITY AS x (a, o)
)
    WHERE jsonb_path_exists(attachments, '$[*] ? (@.kind == "engineer" || @.kind == "operator")');
ALTER TABLE core.connectors FORCE ROW LEVEL SECURITY;
UPDATE core.matrix_versions SET rows = (
    SELECT jsonb_agg(
        CASE WHEN r #>> '{key,kind}' IN ('engineer', 'operator')
            THEN jsonb_set(r, '{key,kind}', to_jsonb(CASE r #>> '{key,kind}' WHEN 'engineer' THEN 'software_engineer' WHEN 'operator' THEN 'ops_analyst' END))
            ELSE r END ORDER BY o)
    FROM jsonb_array_elements(rows) WITH ORDINALITY AS x (r, o)
)
    WHERE jsonb_path_exists(rows, '$[*] ? (@.key.kind == "engineer" || @.key.kind == "operator")');
UPDATE core.benchmarks SET candidate = jsonb_set(candidate, '{kind}', to_jsonb(CASE candidate ->> 'kind' WHEN 'engineer' THEN 'software_engineer' WHEN 'operator' THEN 'ops_analyst' END)) WHERE candidate ->> 'kind' IN ('engineer', 'operator');
UPDATE core.benchmarks SET baseline = jsonb_set(baseline, '{kind}', to_jsonb(CASE baseline ->> 'kind' WHEN 'engineer' THEN 'software_engineer' WHEN 'operator' THEN 'ops_analyst' END)) WHERE baseline ->> 'kind' IN ('engineer', 'operator');
ALTER TABLE core.agent_automations NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_automations SET action = jsonb_set(action, '{agent_kind}', to_jsonb(CASE action ->> 'agent_kind' WHEN 'engineer' THEN 'software_engineer' WHEN 'operator' THEN 'ops_analyst' END)) WHERE action ->> 'agent_kind' IN ('engineer', 'operator');
ALTER TABLE core.agent_automations FORCE ROW LEVEL SECURITY;
ALTER TABLE core.outbox_rows NO FORCE ROW LEVEL SECURITY;
UPDATE core.outbox_rows SET payload = jsonb_set(payload, '{kind}', to_jsonb(CASE payload ->> 'kind' WHEN 'engineer' THEN 'software_engineer' WHEN 'operator' THEN 'ops_analyst' END)) WHERE kind IN ('agent_playbooks.pin.updated', 'agent_playbooks.pin.deleted') AND payload ->> 'kind' IN ('engineer', 'operator');
ALTER TABLE core.outbox_rows FORCE ROW LEVEL SECURITY;

-- The tools' new names move in place where a session pinned them and
-- where a policy's rule or a gate names one.
ALTER TABLE core.agent_sessions NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_sessions SET tools = (
    SELECT jsonb_agg(to_jsonb(CASE t WHEN 'hand_off_to_engineer' THEN 'hand_off_to_software_engineer' ELSE t END) ORDER BY o)
    FROM jsonb_array_elements_text(tools) WITH ORDINALITY AS x (t, o)
)
    WHERE tools ?| ARRAY['hand_off_to_engineer'];
ALTER TABLE core.agent_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE core.tool_policies NO FORCE ROW LEVEL SECURITY;
UPDATE core.tool_policies SET rules = (
    SELECT jsonb_agg(
        CASE WHEN r ->> 'tool' IN ('hand_off_to_engineer')
            THEN jsonb_set(r, '{tool}', to_jsonb(CASE r ->> 'tool' WHEN 'hand_off_to_engineer' THEN 'hand_off_to_software_engineer' ELSE r ->> 'tool' END))
            ELSE r
        END
        ORDER BY o
    )
    FROM jsonb_array_elements(rules) WITH ORDINALITY AS x (r, o)
)
    WHERE jsonb_path_exists(rules, '$[*] ? (@.tool == "hand_off_to_engineer")');
ALTER TABLE core.tool_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE core.agent_playbooks NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_playbooks SET gates = (
    SELECT jsonb_agg(
        CASE WHEN r ->> 'tool' IN ('hand_off_to_engineer')
            THEN jsonb_set(r, '{tool}', to_jsonb(CASE r ->> 'tool' WHEN 'hand_off_to_engineer' THEN 'hand_off_to_software_engineer' ELSE r ->> 'tool' END))
            ELSE r
        END
        ORDER BY o
    )
    FROM jsonb_array_elements(gates) WITH ORDINALITY AS x (r, o)
)
    WHERE jsonb_path_exists(gates, '$[*] ? (@.tool == "hand_off_to_engineer")');
ALTER TABLE core.agent_playbooks FORCE ROW LEVEL SECURITY;
