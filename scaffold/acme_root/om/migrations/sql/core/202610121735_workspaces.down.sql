-- Takes the workspaces back out: each fence, then each table.

DROP POLICY tenant_fence ON core.egress_allowlists;
DROP TABLE core.egress_allowlists;
DROP POLICY tenant_fence ON core.session_workspaces;
DROP TABLE core.session_workspaces;
