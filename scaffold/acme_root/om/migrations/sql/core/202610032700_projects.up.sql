-- Each tenant's projects, each bound to one repository; and the project each
-- session belongs to, one row a session, keyed by the session's id.

CREATE TABLE core.projects (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    name text NOT NULL,
    repository jsonb NOT NULL,
    CONSTRAINT pk_projects PRIMARY KEY (id)
);
CREATE INDEX ix_projects_org_id ON core.projects (org_id);

CREATE TABLE core.session_projects (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    project_id uuid NOT NULL,
    CONSTRAINT pk_session_projects PRIMARY KEY (id)
);
CREATE INDEX ix_session_projects_org_id ON core.session_projects (org_id);

-- The second fence: the transaction's own tenant, or the system scope to the
-- system login alone (ADR 0016). The serving logins' grants come from the
-- role's default privileges.

ALTER TABLE core.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.projects FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.projects
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'acme_system'
        )
    )
    WITH CHECK (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'acme_system'
        )
    );

ALTER TABLE core.session_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.session_projects FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.session_projects
    USING (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'acme_system'
        )
    )
    WITH CHECK (
        org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
        OR (
            current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
            AND current_user = 'acme_system'
        )
    );

-- A session's project is written once. The role's default privileges grant
-- the serving logins every DML statement on a new table; here they keep
-- SELECT and INSERT, so no statement a process sends moves a session to
-- another project. The purge login takes the row with its session, or with
-- its tenant, within the tenant the fence admits (ADR 1010).

REVOKE UPDATE, DELETE ON core.session_projects FROM acme_runtime, acme_system;
GRANT SELECT, DELETE ON core.session_projects TO acme_purge;
