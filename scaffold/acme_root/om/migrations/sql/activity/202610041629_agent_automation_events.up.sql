-- An automation is an agent automation: the kinds of the events it
-- announced move in place.

-- The kinds of the events they announce move in place.
ALTER TABLE activity.change_events NO FORCE ROW LEVEL SECURITY;
UPDATE activity.change_events SET kind = CASE kind
        WHEN 'automations.automation.created' THEN 'agent_automations.agent_automation.created'
        WHEN 'automations.automation.updated' THEN 'agent_automations.agent_automation.updated'
        WHEN 'automations.principal.granted' THEN 'agent_automations.principal.granted'
    END
    WHERE kind IN ('automations.automation.created', 'automations.automation.updated', 'automations.principal.granted');
UPDATE activity.change_events
    SET payload = jsonb_set(payload, '{kind}', to_jsonb(CASE payload ->> 'kind'
        WHEN 'automations.automation.created' THEN 'agent_automations.agent_automation.created'
        WHEN 'automations.automation.updated' THEN 'agent_automations.agent_automation.updated'
        WHEN 'automations.principal.granted' THEN 'agent_automations.principal.granted'
    END))
    WHERE kind = 'outbox.row.failed' AND payload ->> 'kind' IN ('automations.automation.created', 'automations.automation.updated', 'automations.principal.granted');
ALTER TABLE activity.change_events FORCE ROW LEVEL SECURITY;
