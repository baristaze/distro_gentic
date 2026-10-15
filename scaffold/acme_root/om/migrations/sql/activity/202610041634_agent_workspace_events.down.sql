-- The release before reads the names it wrote. Every row stays.

ALTER TABLE activity.change_events NO FORCE ROW LEVEL SECURITY;
UPDATE activity.change_events SET kind = CASE kind
        WHEN 'agent_workspaces.egress_allowlist.created' THEN 'workspaces.egress_allowlist.created'
        WHEN 'agent_workspaces.egress_allowlist.updated' THEN 'workspaces.egress_allowlist.updated'
        WHEN 'exec_relay.agent_workspace_binding.updated' THEN 'exec_relay.workspace_binding.updated'
    END
    WHERE kind IN ('agent_workspaces.egress_allowlist.created', 'agent_workspaces.egress_allowlist.updated', 'exec_relay.agent_workspace_binding.updated');
UPDATE activity.change_events
    SET payload = jsonb_set(payload, '{kind}', to_jsonb(CASE payload ->> 'kind'
        WHEN 'agent_workspaces.egress_allowlist.created' THEN 'workspaces.egress_allowlist.created'
        WHEN 'agent_workspaces.egress_allowlist.updated' THEN 'workspaces.egress_allowlist.updated'
        WHEN 'exec_relay.agent_workspace_binding.updated' THEN 'exec_relay.workspace_binding.updated'
    END))
    WHERE kind = 'outbox.row.failed' AND payload ->> 'kind' IN ('agent_workspaces.egress_allowlist.created', 'agent_workspaces.egress_allowlist.updated', 'exec_relay.agent_workspace_binding.updated');
ALTER TABLE activity.change_events FORCE ROW LEVEL SECURITY;
