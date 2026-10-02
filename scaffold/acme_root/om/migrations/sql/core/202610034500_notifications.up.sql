-- Whose authority an automation runs on, the tenant's automation
-- principal, the accounts of a user read as their channels, and who was
-- told what waits on them. Each new table names its tenant and sits behind
-- the tenant fence.

-- An automation runs as its creator unless it says otherwise.
ALTER TABLE core.automations ADD COLUMN runs_as text NOT NULL DEFAULT 'creator';
ALTER TABLE core.automations ALTER COLUMN runs_as DROP DEFAULT;

-- The tenant's automation principal, one row a tenant.
CREATE TABLE core.automation_principals (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    role text NOT NULL,
    granted_by uuid NOT NULL,
    CONSTRAINT pk_automation_principals PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_automation_principals_org_id ON core.automation_principals (org_id);

-- A user's accounts, read as the channels a notification reaches them on.
CREATE INDEX ix_account_links_org_id_user_id ON core.account_links (org_id, user_id);

-- Who was told what waits on them, on which channel, once a park.
CREATE TABLE core.notifications (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    recipient uuid NOT NULL,
    session_id uuid NOT NULL,
    park_step uuid NOT NULL,
    reason text NOT NULL,
    unlock text NOT NULL,
    action text NOT NULL,
    link text NOT NULL,
    channel text NOT NULL,
    address text NOT NULL,
    provenance text,
    text text NOT NULL,
    CONSTRAINT pk_notifications PRIMARY KEY (id)
);
CREATE INDEX ix_notifications_org_id_recipient_created_at ON core.notifications (org_id, recipient, created_at);

ALTER TABLE core.automation_principals ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.automation_principals FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.automation_principals
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

ALTER TABLE core.notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.notifications FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.notifications
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
