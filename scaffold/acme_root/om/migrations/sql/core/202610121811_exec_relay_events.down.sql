-- The release before reads the names it wrote. Every row stays.

ALTER TABLE core.outbox_rows NO FORCE ROW LEVEL SECURITY;
UPDATE core.outbox_rows SET kind = CASE kind
        WHEN 'exec_relay.exec_control.created' THEN 'relay.exec_control.created'
        WHEN 'exec_relay.workspace_binding.updated' THEN 'relay.workspace_binding.updated'
    END
    WHERE kind IN ('exec_relay.exec_control.created', 'exec_relay.workspace_binding.updated');
ALTER TABLE core.outbox_rows FORCE ROW LEVEL SECURITY;
