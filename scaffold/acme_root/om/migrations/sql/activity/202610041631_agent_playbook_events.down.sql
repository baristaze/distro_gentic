-- The release before reads the names it wrote. Every row stays.

ALTER TABLE activity.change_events NO FORCE ROW LEVEL SECURITY;
UPDATE activity.change_events SET kind = CASE kind
        WHEN 'agent_playbooks.agent_playbook.created' THEN 'playbooks.playbook.created'
        WHEN 'agent_playbooks.pin.updated' THEN 'playbooks.pin.updated'
        WHEN 'agent_playbooks.pin.deleted' THEN 'playbooks.pin.deleted'
    END
    WHERE kind IN ('agent_playbooks.agent_playbook.created', 'agent_playbooks.pin.updated', 'agent_playbooks.pin.deleted');
UPDATE activity.change_events
    SET payload = jsonb_set(payload, '{kind}', to_jsonb(CASE payload ->> 'kind'
        WHEN 'agent_playbooks.agent_playbook.created' THEN 'playbooks.playbook.created'
        WHEN 'agent_playbooks.pin.updated' THEN 'playbooks.pin.updated'
        WHEN 'agent_playbooks.pin.deleted' THEN 'playbooks.pin.deleted'
    END))
    WHERE kind = 'outbox.row.failed' AND payload ->> 'kind' IN ('agent_playbooks.agent_playbook.created', 'agent_playbooks.pin.updated', 'agent_playbooks.pin.deleted');
ALTER TABLE activity.change_events FORCE ROW LEVEL SECURITY;
