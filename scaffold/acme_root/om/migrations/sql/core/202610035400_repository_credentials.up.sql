-- That a project's repository has a fetch credential, one row a project
-- under the project's id, behind the tenant fence: who gave it, and when.
-- Its value is in the tenant's store, never here. And the digest of the
-- one push token a session's loop holds, with when it expires.

CREATE TABLE core.repository_credentials (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    version integer NOT NULL,
    CONSTRAINT pk_repository_credentials PRIMARY KEY (id)
);
CREATE INDEX ix_repository_credentials_org_id ON core.repository_credentials (org_id);

ALTER TABLE core.session_workspaces ADD COLUMN push_digest text;
ALTER TABLE core.session_workspaces ADD COLUMN push_expires_at timestamptz;

ALTER TABLE core.repository_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.repository_credentials FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.repository_credentials
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
