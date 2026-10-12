-- Takes the repository credentials back out: the push token's columns,
-- the fence, then the table.

ALTER TABLE core.session_workspaces DROP COLUMN push_expires_at;
ALTER TABLE core.session_workspaces DROP COLUMN push_digest;
DROP POLICY tenant_fence ON core.repository_credentials;
DROP TABLE core.repository_credentials;
