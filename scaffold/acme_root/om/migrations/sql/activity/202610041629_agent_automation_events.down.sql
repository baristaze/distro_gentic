-- The release before reads the names it wrote. Every row stays.

ALTER TABLE activity.change_events NO FORCE ROW LEVEL SECURITY;
UPDATE activity.change_events SET kind = CASE kind
        WHEN 'agent_automations.agent_automation.created' THEN 'automations.automation.created'
        WHEN 'agent_automations.agent_automation.updated' THEN 'automations.automation.updated'
        WHEN 'agent_automations.principal.granted' THEN 'automations.principal.granted'
    END
    WHERE kind IN ('agent_automations.agent_automation.created', 'agent_automations.agent_automation.updated', 'agent_automations.principal.granted');
UPDATE activity.change_events
    SET payload = jsonb_set(payload, '{kind}', to_jsonb(CASE payload ->> 'kind'
        WHEN 'agent_automations.agent_automation.created' THEN 'automations.automation.created'
        WHEN 'agent_automations.agent_automation.updated' THEN 'automations.automation.updated'
        WHEN 'agent_automations.principal.granted' THEN 'automations.principal.granted'
    END))
    WHERE kind = 'outbox.row.failed' AND payload ->> 'kind' IN ('agent_automations.agent_automation.created', 'agent_automations.agent_automation.updated', 'agent_automations.principal.granted');
ALTER TABLE activity.change_events FORCE ROW LEVEL SECURITY;
