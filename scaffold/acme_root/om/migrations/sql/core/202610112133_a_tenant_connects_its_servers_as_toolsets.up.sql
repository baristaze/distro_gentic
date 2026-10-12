-- A tenant's connectors: its servers, the tools of each a person reviewed,
-- pinned by their definitions' hashes, and the kinds each is attached to.
-- A credential is never here: a cloud connector names the tenant's secret
-- that holds it, and a host connector's stays on its host.
CREATE TABLE core.connectors (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    name text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    summary text NOT NULL,
    place text NOT NULL,
    url text,
    credential_header text NOT NULL,
    credential_scheme text NOT NULL,
    secret text,
    host_server text,
    tools jsonb NOT NULL,
    review integer NOT NULL,
    reviewed_by uuid,
    attachments jsonb NOT NULL,
    version integer NOT NULL,
    CONSTRAINT pk_connectors PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_connectors_org_id_name ON core.connectors (org_id, name);

ALTER TABLE core.connectors ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.connectors FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.connectors
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

-- What each session pinned of its tenant's connectors as its first run
-- began, written once, so its tool definitions never move under it.
CREATE TABLE core.session_connectors (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    connectors jsonb NOT NULL,
    CONSTRAINT pk_session_connectors PRIMARY KEY (id)
);
CREATE INDEX ix_session_connectors_org_id ON core.session_connectors (org_id);

ALTER TABLE core.session_connectors ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.session_connectors FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.session_connectors
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
