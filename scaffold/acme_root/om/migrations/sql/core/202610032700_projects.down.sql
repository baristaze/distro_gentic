-- Takes the projects back out: each grant, each fence, then each table.

REVOKE SELECT, DELETE ON core.session_projects FROM acme_purge;
DROP POLICY tenant_fence ON core.session_projects;
DROP TABLE core.session_projects;
DROP POLICY tenant_fence ON core.projects;
DROP TABLE core.projects;
