-- Each tenant's retention policy, one row a tenant, with its projects'
-- narrowings; and each session's snapshot of it, taken as the session is
-- created, which the sweep tightens and acts on when it expires.

CREATE TABLE core.retention_policies (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    policy jsonb NOT NULL,
    projects jsonb NOT NULL,
    version integer NOT NULL,
    CONSTRAINT pk_retention_policies PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_retention_policies_org_id ON core.retention_policies (org_id);

CREATE TABLE core.session_retention (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    session_id uuid NOT NULL,
    project_id uuid,
    policy jsonb NOT NULL,
    policy_version integer NOT NULL,
    at_rest boolean NOT NULL,
    content_expires_at timestamptz,
    shape_expires_at timestamptz,
    content_expired_at timestamptz,
    destruction jsonb,
    shape_expired_at timestamptz,
    version integer NOT NULL,
    CONSTRAINT pk_session_retention PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_session_retention_org_id_session_id
    ON core.session_retention (org_id, session_id);
CREATE INDEX ix_session_retention_org_id_policy_version
    ON core.session_retention (org_id, policy_version);
-- The sweep's reads across tenants: what is still to expire, by when.
CREATE INDEX ix_session_retention_content_expires_at
    ON core.session_retention (content_expires_at)
    WHERE content_expires_at IS NOT NULL AND content_expired_at IS NULL;
CREATE INDEX ix_session_retention_shape_expires_at
    ON core.session_retention (shape_expires_at)
    WHERE shape_expires_at IS NOT NULL AND shape_expired_at IS NULL;

-- The second fence: the transaction's own tenant, or the system scope to the
-- system login alone (ADR 0016). The serving logins' grants come from the
-- role's default privileges.

ALTER TABLE core.retention_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.retention_policies FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.retention_policies
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

ALTER TABLE core.session_retention ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.session_retention FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.session_retention
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
