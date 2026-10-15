-- The platform's relay is the exec relay, apart from the outbox's.

-- The kinds of the events they announce move in place.
ALTER TABLE activity.change_events NO FORCE ROW LEVEL SECURITY;
UPDATE activity.change_events SET kind = CASE kind
        WHEN 'relay.exec_control.created' THEN 'exec_relay.exec_control.created'
        WHEN 'relay.workspace_binding.updated' THEN 'exec_relay.workspace_binding.updated'
    END
    WHERE kind IN ('relay.exec_control.created', 'relay.workspace_binding.updated');
UPDATE activity.change_events
    SET payload = jsonb_set(payload, '{kind}', to_jsonb(CASE payload ->> 'kind'
        WHEN 'relay.exec_control.created' THEN 'exec_relay.exec_control.created'
        WHEN 'relay.workspace_binding.updated' THEN 'exec_relay.workspace_binding.updated'
    END))
    WHERE kind = 'outbox.row.failed' AND payload ->> 'kind' IN ('relay.exec_control.created', 'relay.workspace_binding.updated');
ALTER TABLE activity.change_events FORCE ROW LEVEL SECURITY;
