-- The platform's relay is the exec relay, apart from the outbox's.

-- The kinds of the events they announce move in place.
ALTER TABLE core.outbox_rows NO FORCE ROW LEVEL SECURITY;
UPDATE core.outbox_rows SET kind = CASE kind
        WHEN 'relay.exec_control.created' THEN 'exec_relay.exec_control.created'
        WHEN 'relay.workspace_binding.updated' THEN 'exec_relay.workspace_binding.updated'
    END
    WHERE kind IN ('relay.exec_control.created', 'relay.workspace_binding.updated');
ALTER TABLE core.outbox_rows FORCE ROW LEVEL SECURITY;
