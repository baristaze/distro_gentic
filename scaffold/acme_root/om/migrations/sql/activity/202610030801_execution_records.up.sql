-- Every run, written once: the version and the environment it ran in,
-- who ran it, the check, and the provenance of each dependency. A
-- validation is one pass of the executor's, written with the runs it lists
-- in one commit; a hypothesis or a finding links the runs that show it.

CREATE TABLE activity.execution_records (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    session_id uuid NOT NULL,
    project text NOT NULL,
    purpose text NOT NULL,
    step_id uuid,
    validation_id uuid,
    version text NOT NULL,
    dirty boolean NOT NULL,
    environment jsonb NOT NULL,
    host text NOT NULL,
    isolation text NOT NULL,
    executor text NOT NULL,
    "check" text NOT NULL,
    check_version text NOT NULL,
    parameters jsonb NOT NULL,
    metrics jsonb NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz NOT NULL,
    outcome text NOT NULL,
    cases jsonb NOT NULL,
    artifacts jsonb NOT NULL,
    dependencies jsonb NOT NULL,
    abort text,
    CONSTRAINT pk_execution_records PRIMARY KEY (id)
);
CREATE INDEX ix_execution_records_org_id_session_id_id
    ON activity.execution_records (org_id, session_id, id);
CREATE INDEX ix_execution_records_org_id_validation_id
    ON activity.execution_records (org_id, validation_id);

CREATE TABLE activity.validations (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    session_id uuid NOT NULL,
    project text NOT NULL,
    purpose text NOT NULL,
    version text NOT NULL,
    source text NOT NULL,
    executor text NOT NULL,
    results_sha256 text NOT NULL,
    records jsonb NOT NULL,
    CONSTRAINT pk_validations PRIMARY KEY (id)
);
CREATE INDEX ix_validations_org_id_session_id_id
    ON activity.validations (org_id, session_id, id);

CREATE TABLE activity.inferences (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    session_id uuid NOT NULL,
    step_id uuid NOT NULL,
    kind text NOT NULL,
    resolves uuid,
    stance text,
    supports jsonb NOT NULL,
    refutes jsonb NOT NULL,
    CONSTRAINT pk_inferences PRIMARY KEY (id)
);
CREATE INDEX ix_inferences_org_id_session_id_id
    ON activity.inferences (org_id, session_id, id);

-- The second fence on each: the transaction's own tenant, or the system
-- scope to the system login alone (ADR 0016).

ALTER TABLE activity.execution_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity.execution_records FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON activity.execution_records
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

ALTER TABLE activity.validations ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity.validations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON activity.validations
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

ALTER TABLE activity.inferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity.inferences FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON activity.inferences
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

-- Written once, like the history they belong to: the serving logins keep
-- SELECT and INSERT (ADR 1002). The purge login takes them with their
-- session or their tenant, and holds SELECT and DELETE on them and nothing
-- else (ADR 1010).

REVOKE UPDATE, DELETE ON activity.execution_records FROM acme_runtime, acme_system;
REVOKE UPDATE, DELETE ON activity.validations FROM acme_runtime, acme_system;
REVOKE UPDATE, DELETE ON activity.inferences FROM acme_runtime, acme_system;
GRANT SELECT, DELETE ON activity.execution_records TO acme_purge;
GRANT SELECT, DELETE ON activity.validations TO acme_purge;
GRANT SELECT, DELETE ON activity.inferences TO acme_purge;
