-- The cloud pool's limits, which its operators write and each claim reads:
-- one row per version of the pool's own, the platform's, and one row per
-- tenant an operator gave a maximum of its own.

CREATE TABLE core.pool_limits (
    id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    warm integer NOT NULL,
    most integer NOT NULL,
    tenant_most integer NOT NULL,
    version integer NOT NULL,
    CONSTRAINT pk_pool_limits PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_pool_limits_version ON core.pool_limits (version);

CREATE TABLE core.pool_tenant_limits (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    most integer NOT NULL,
    version integer NOT NULL,
    CONSTRAINT pk_pool_tenant_limits PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_pool_tenant_limits_org_id ON core.pool_tenant_limits (org_id);
ALTER TABLE core.pool_tenant_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.pool_tenant_limits FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.pool_tenant_limits
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
