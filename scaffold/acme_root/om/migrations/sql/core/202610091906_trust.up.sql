-- The trust swimlane's rows. No column holds a secret's value or a key's:
-- a declaration names a secret and the store that holds it, and a key's row
-- is its reference, which names its value in the secret store.

CREATE TABLE core.secret_declarations (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    name text NOT NULL,
    variable text NOT NULL,
    owner_kind text NOT NULL,
    owner_id uuid NOT NULL,
    scope text NOT NULL,
    store text NOT NULL,
    CONSTRAINT pk_secret_declarations PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_secret_declarations_org_id_name ON core.secret_declarations (org_id, name);

-- One live key a provider in a tenant: the partial unique index guards the
-- writes, and no read plans on it.
CREATE TABLE core.provider_keys (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    provider text NOT NULL,
    status text NOT NULL,
    last_used_at timestamptz,
    version integer NOT NULL,
    CONSTRAINT pk_provider_keys PRIMARY KEY (id)
);
CREATE INDEX ix_provider_keys_org_id_created_at ON core.provider_keys (org_id, created_at);
CREATE UNIQUE INDEX uq_provider_keys_org_id_provider_live ON core.provider_keys (org_id, provider) WHERE status = 'live';

-- An operator's grant to open one tenant's session content, until it expires.
CREATE TABLE core.content_grants (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    identity_id uuid NOT NULL,
    expires_at timestamptz NOT NULL,
    CONSTRAINT pk_content_grants PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_content_grants_org_id_identity_id ON core.content_grants (org_id, identity_id);

-- The second fence on each: the transaction's own tenant, or the system
-- scope to the system login alone (ADR 0016). The serving logins' grants
-- come from the role's default privileges.

ALTER TABLE core.secret_declarations ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.secret_declarations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.secret_declarations
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

ALTER TABLE core.provider_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.provider_keys FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.provider_keys
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

ALTER TABLE core.content_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.content_grants FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.content_grants
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
