-- The installations a tenant connects, each naming one tenant across every
-- tenant, behind the tenant fence; and when a person read a notification.

-- A system's installation of the platform, connected by one tenant: the
-- unique index spans every tenant.
CREATE TABLE core.installations (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    integration text NOT NULL,
    installation text NOT NULL,
    created_by uuid NOT NULL,
    CONSTRAINT pk_installations PRIMARY KEY (id)
);
CREATE INDEX ix_installations_org_id ON core.installations (org_id);
CREATE UNIQUE INDEX uq_installations_integration_installation ON core.installations (integration, installation);

-- A notification its recipient read.
ALTER TABLE core.notifications ADD COLUMN read_at timestamptz;

ALTER TABLE core.installations ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.installations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.installations
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
