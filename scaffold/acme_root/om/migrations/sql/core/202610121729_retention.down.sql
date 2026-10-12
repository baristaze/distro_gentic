-- Takes retention back out: each fence, then each table.

DROP POLICY tenant_fence ON core.session_retention;
DROP TABLE core.session_retention;
DROP POLICY tenant_fence ON core.retention_policies;
DROP TABLE core.retention_policies;
