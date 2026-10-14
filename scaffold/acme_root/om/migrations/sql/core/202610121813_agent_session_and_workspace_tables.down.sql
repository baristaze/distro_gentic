-- The release before reads the names it wrote. Every row stays.

ALTER TABLE core.outbox_rows NO FORCE ROW LEVEL SECURITY;
UPDATE core.outbox_rows SET kind = CASE kind
        WHEN 'agent_workspaces.egress_allowlist.created' THEN 'workspaces.egress_allowlist.created'
        WHEN 'agent_workspaces.egress_allowlist.updated' THEN 'workspaces.egress_allowlist.updated'
        WHEN 'exec_relay.agent_workspace_binding.updated' THEN 'exec_relay.workspace_binding.updated'
    END
    WHERE kind IN ('agent_workspaces.egress_allowlist.created', 'agent_workspaces.egress_allowlist.updated', 'exec_relay.agent_workspace_binding.updated');
ALTER TABLE core.outbox_rows FORCE ROW LEVEL SECURITY;

ALTER TABLE core.pool_vms RENAME CONSTRAINT pk_pool_vms TO pk_pool_machines;
ALTER INDEX core.ix_pool_vms_tenant_id_session_id RENAME TO ix_pool_machines_tenant_id_session_id;
ALTER INDEX core.uq_pool_vms_key_digest RENAME TO uq_pool_machines_key_digest;
ALTER INDEX core.uq_pool_vms_name RENAME TO uq_pool_machines_name;
ALTER TABLE core.pool_vms RENAME TO pool_machines;

ALTER TABLE core.agent_workspace_bindings RENAME CONSTRAINT pk_agent_workspace_bindings TO pk_workspace_bindings;
ALTER INDEX core.uq_agent_workspace_bindings_org_id_session_id RENAME TO uq_workspace_bindings_org_id_session_id;
ALTER TABLE core.agent_workspace_bindings RENAME TO workspace_bindings;

ALTER TABLE core.agent_workspace_snapshots RENAME CONSTRAINT pk_agent_workspace_snapshots TO pk_workspace_snapshots;
ALTER INDEX core.ix_agent_workspace_snapshots_org_id_session_id RENAME TO ix_workspace_snapshots_org_id_session_id;
ALTER TABLE core.agent_workspace_snapshots RENAME TO workspace_snapshots;

ALTER TABLE core.agent_session_workspaces RENAME CONSTRAINT pk_agent_session_workspaces TO pk_session_workspaces;
ALTER INDEX core.ix_agent_session_workspaces_org_id RENAME TO ix_session_workspaces_org_id;
ALTER TABLE core.agent_session_workspaces RENAME TO session_workspaces;

ALTER TABLE core.agent_session_connectors RENAME CONSTRAINT pk_agent_session_connectors TO pk_session_connectors;
ALTER INDEX core.ix_agent_session_connectors_org_id RENAME TO ix_session_connectors_org_id;
ALTER TABLE core.agent_session_connectors RENAME TO session_connectors;

ALTER TABLE core.agent_session_placements RENAME CONSTRAINT pk_agent_session_placements TO pk_session_placements;
ALTER INDEX core.uq_agent_session_placements_org_id_session_id RENAME TO uq_session_placements_org_id_session_id;
ALTER TABLE core.agent_session_placements RENAME TO session_placements;

ALTER TABLE core.agent_session_retention RENAME CONSTRAINT pk_agent_session_retention TO pk_session_retention;
ALTER INDEX core.ix_agent_session_retention_content_expires_at RENAME TO ix_session_retention_content_expires_at;
ALTER INDEX core.ix_agent_session_retention_org_id_policy_version RENAME TO ix_session_retention_org_id_policy_version;
ALTER INDEX core.ix_agent_session_retention_shape_expires_at RENAME TO ix_session_retention_shape_expires_at;
ALTER INDEX core.uq_agent_session_retention_org_id_session_id RENAME TO uq_session_retention_org_id_session_id;
ALTER TABLE core.agent_session_retention RENAME TO session_retention;
