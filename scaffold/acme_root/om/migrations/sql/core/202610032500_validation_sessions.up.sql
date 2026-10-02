-- A validation session: a check run on a station with no agent. It holds
-- what the lab's daemon runs and where, and the execution record of its
-- run once it is recorded. Its station work is a work item of its own.

CREATE TABLE core.validation_sessions (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    lab_id uuid NOT NULL,
    check_name text NOT NULL,
    check_version text NOT NULL,
    parameters jsonb NOT NULL,
    status text NOT NULL,
    run_id uuid,
    finished_at timestamptz,
    version integer NOT NULL,
    CONSTRAINT pk_validation_sessions PRIMARY KEY (id)
);
CREATE INDEX ix_validation_sessions_org_id ON core.validation_sessions (org_id);

-- The second fence: the transaction's own tenant, or the system scope to the
-- system login alone (ADR 0016). The serving logins' grants come from the
-- role's default privileges.

ALTER TABLE core.validation_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.validation_sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.validation_sessions
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
