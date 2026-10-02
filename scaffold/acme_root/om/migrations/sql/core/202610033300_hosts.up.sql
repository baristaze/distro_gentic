-- A tenant's host pools, the tokens that enroll hosts into them, the hosts
-- with their own credentials, and where each placed session runs. A token's
-- and a credential's digest is unique across tenants, since a host's call
-- names no tenant and the digest is how it is found (ADR 2003).

CREATE TABLE core.host_pools (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    name text NOT NULL,
    region text NOT NULL,
    labels jsonb NOT NULL,
    CONSTRAINT pk_host_pools PRIMARY KEY (id)
);
CREATE INDEX ix_host_pools_org_id ON core.host_pools (org_id);

CREATE TABLE core.host_enrollment_tokens (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    pool_id uuid NOT NULL,
    digest text NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    revoked_by uuid,
    CONSTRAINT pk_host_enrollment_tokens PRIMARY KEY (id)
);
CREATE INDEX ix_host_enrollment_tokens_org_id ON core.host_enrollment_tokens (org_id);
CREATE UNIQUE INDEX uq_host_enrollment_tokens_digest ON core.host_enrollment_tokens (digest);

CREATE TABLE core.hosts (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    pool_id uuid NOT NULL,
    name text NOT NULL,
    enrolled_with uuid NOT NULL,
    advertisement jsonb NOT NULL,
    exec_version integer NOT NULL,
    last_seen_at timestamptz NOT NULL,
    revoked_at timestamptz,
    revoked_by uuid,
    CONSTRAINT pk_hosts PRIMARY KEY (id)
);
CREATE INDEX ix_hosts_org_id_pool_id ON core.hosts (org_id, pool_id);

CREATE TABLE core.host_credentials (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    host_id uuid NOT NULL,
    digest text NOT NULL,
    expires_at timestamptz NOT NULL,
    rotated_at timestamptz,
    CONSTRAINT pk_host_credentials PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_host_credentials_digest ON core.host_credentials (digest);
CREATE INDEX ix_host_credentials_org_id_host_id ON core.host_credentials (org_id, host_id);

CREATE TABLE core.session_placements (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    session_id uuid NOT NULL,
    pool_id uuid,
    version integer NOT NULL,
    CONSTRAINT pk_session_placements PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_session_placements_org_id_session_id
    ON core.session_placements (org_id, session_id);

-- The second fence: the transaction's own tenant, or the system scope to the
-- system login alone (ADR 0016). The serving logins' grants come from the
-- role's default privileges.

ALTER TABLE core.host_pools ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.host_pools FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.host_pools
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

ALTER TABLE core.host_enrollment_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.host_enrollment_tokens FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.host_enrollment_tokens
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

ALTER TABLE core.hosts ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.hosts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.hosts
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

ALTER TABLE core.host_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.host_credentials FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.host_credentials
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

ALTER TABLE core.session_placements ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.session_placements FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.session_placements
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
