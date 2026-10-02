-- Takes the hosts back out: each fence, then each table.

DROP POLICY tenant_fence ON core.session_placements;
DROP POLICY tenant_fence ON core.host_credentials;
DROP POLICY tenant_fence ON core.hosts;
DROP POLICY tenant_fence ON core.host_enrollment_tokens;
DROP POLICY tenant_fence ON core.host_pools;
DROP TABLE core.session_placements;
DROP TABLE core.host_credentials;
DROP TABLE core.hosts;
DROP TABLE core.host_enrollment_tokens;
DROP TABLE core.host_pools;
