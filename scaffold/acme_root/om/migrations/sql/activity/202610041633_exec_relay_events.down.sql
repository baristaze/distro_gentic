-- The release before reads the names it wrote. Every row stays.

ALTER TABLE activity.events NO FORCE ROW LEVEL SECURITY;
UPDATE activity.events SET kind = CASE kind
        WHEN 'exec_relay.exec_control.created' THEN 'relay.exec_control.created'
        WHEN 'exec_relay.workspace_binding.updated' THEN 'relay.workspace_binding.updated'
    END
    WHERE kind IN ('exec_relay.exec_control.created', 'exec_relay.workspace_binding.updated');
UPDATE activity.events
    SET payload = jsonb_set(payload, '{kind}', to_jsonb(CASE payload ->> 'kind'
        WHEN 'exec_relay.exec_control.created' THEN 'relay.exec_control.created'
        WHEN 'exec_relay.workspace_binding.updated' THEN 'relay.workspace_binding.updated'
    END))
    WHERE kind = 'outbox.row.failed' AND payload ->> 'kind' IN ('exec_relay.exec_control.created', 'exec_relay.workspace_binding.updated');
ALTER TABLE activity.events FORCE ROW LEVEL SECURITY;
