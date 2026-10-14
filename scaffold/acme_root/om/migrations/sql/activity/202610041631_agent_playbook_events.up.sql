-- A playbook is an agent playbook: the kinds of the events it announced
-- move in place.

-- The kinds of the events they announce move in place.
ALTER TABLE activity.events NO FORCE ROW LEVEL SECURITY;
UPDATE activity.events SET kind = CASE kind
        WHEN 'playbooks.playbook.created' THEN 'agent_playbooks.agent_playbook.created'
        WHEN 'playbooks.pin.updated' THEN 'agent_playbooks.pin.updated'
        WHEN 'playbooks.pin.deleted' THEN 'agent_playbooks.pin.deleted'
    END
    WHERE kind IN ('playbooks.playbook.created', 'playbooks.pin.updated', 'playbooks.pin.deleted');
UPDATE activity.events
    SET payload = jsonb_set(payload, '{kind}', to_jsonb(CASE payload ->> 'kind'
        WHEN 'playbooks.playbook.created' THEN 'agent_playbooks.agent_playbook.created'
        WHEN 'playbooks.pin.updated' THEN 'agent_playbooks.pin.updated'
        WHEN 'playbooks.pin.deleted' THEN 'agent_playbooks.pin.deleted'
    END))
    WHERE kind = 'outbox.row.failed' AND payload ->> 'kind' IN ('playbooks.playbook.created', 'playbooks.pin.updated', 'playbooks.pin.deleted');
ALTER TABLE activity.events FORCE ROW LEVEL SECURITY;
