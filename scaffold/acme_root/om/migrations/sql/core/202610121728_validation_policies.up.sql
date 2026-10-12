-- Each project's validation policy, one row a project of a tenant: the
-- checks it declares, the ones a change must pass, and the paths an agent
-- may not change.

CREATE TABLE core.validation_policies (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    project text NOT NULL,
    checks jsonb NOT NULL,
    requirements jsonb NOT NULL,
    protected jsonb NOT NULL,
    version integer NOT NULL,
    CONSTRAINT pk_validation_policies PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_validation_policies_org_id_project
    ON core.validation_policies (org_id, project);

-- The second fence: the transaction's own tenant, or the system scope to the
-- system login alone (ADR 0016). The serving logins' grants come from the
-- role's default privileges.

ALTER TABLE core.validation_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.validation_policies FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.validation_policies
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
