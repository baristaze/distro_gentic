-- Each session's workspace, one row a session under its id: the isolation
-- pinned when the session was created (its level, its limits, its egress
-- and where that came from), and what the cache knows between loops (its
-- branch, whether the remote has held it, the last snapshot of its work,
-- and what the next loop is told). And each project's egress allowlist,
-- one row a project: its destinations and methods, or open egress with the
-- reason it was chosen.

CREATE TABLE core.session_workspaces (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    project_id uuid,
    level text NOT NULL,
    limits jsonb NOT NULL,
    egress text NOT NULL,
    rules jsonb NOT NULL,
    egress_source text NOT NULL,
    branch text NOT NULL,
    branch_seen boolean NOT NULL,
    snapshot_ref text,
    notice text,
    version integer NOT NULL,
    CONSTRAINT pk_session_workspaces PRIMARY KEY (id)
);
CREATE INDEX ix_session_workspaces_org_id ON core.session_workspaces (org_id);

CREATE TABLE core.egress_allowlists (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    project_id uuid NOT NULL,
    rules jsonb NOT NULL,
    open boolean NOT NULL,
    reason text,
    version integer NOT NULL,
    CONSTRAINT pk_egress_allowlists PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_egress_allowlists_org_id_project_id
    ON core.egress_allowlists (org_id, project_id);

-- The second fence: the transaction's own tenant, or the system scope to the
-- system login alone (ADR 0016). The serving logins' grants come from the
-- role's default privileges.

ALTER TABLE core.session_workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.session_workspaces FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.session_workspaces
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

ALTER TABLE core.egress_allowlists ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.egress_allowlists FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.egress_allowlists
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
