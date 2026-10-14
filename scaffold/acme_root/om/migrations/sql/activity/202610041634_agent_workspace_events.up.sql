-- The platform's workspaces are its agent workspaces.

-- The kinds of the events they announce move in place.
ALTER TABLE activity.events NO FORCE ROW LEVEL SECURITY;
UPDATE activity.events SET kind = CASE kind
        WHEN 'workspaces.egress_allowlist.created' THEN 'agent_workspaces.egress_allowlist.created'
        WHEN 'workspaces.egress_allowlist.updated' THEN 'agent_workspaces.egress_allowlist.updated'
        WHEN 'exec_relay.workspace_binding.updated' THEN 'exec_relay.agent_workspace_binding.updated'
    END
    WHERE kind IN ('workspaces.egress_allowlist.created', 'workspaces.egress_allowlist.updated', 'exec_relay.workspace_binding.updated');
UPDATE activity.events
    SET payload = jsonb_set(payload, '{kind}', to_jsonb(CASE payload ->> 'kind'
        WHEN 'workspaces.egress_allowlist.created' THEN 'agent_workspaces.egress_allowlist.created'
        WHEN 'workspaces.egress_allowlist.updated' THEN 'agent_workspaces.egress_allowlist.updated'
        WHEN 'exec_relay.workspace_binding.updated' THEN 'exec_relay.agent_workspace_binding.updated'
    END))
    WHERE kind = 'outbox.row.failed' AND payload ->> 'kind' IN ('workspaces.egress_allowlist.created', 'workspaces.egress_allowlist.updated', 'exec_relay.workspace_binding.updated');
ALTER TABLE activity.events FORCE ROW LEVEL SECURITY;
