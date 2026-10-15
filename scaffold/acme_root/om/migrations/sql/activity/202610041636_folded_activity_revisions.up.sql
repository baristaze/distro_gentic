-- The platform's own tables of the activity role, on the engine's: the
-- execution record of each run, the validations, the inferences, and the
-- spend ledger with its counts; and an index of the spend budgets' holds
-- by their opening time, which bounds the sweep's read of the holds no
-- settlement closed. Each table is fenced to its tenant (ADR 0016). The
-- serving logins' grants come from the role's default privileges, less
-- UPDATE and DELETE on what is written once (ADR 2009, ADR 2011); the
-- purge login reaches the execution records, the validations, and the
-- inferences, within the tenant its transaction names (ADR 1010).

CREATE TABLE activity.execution_records (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    agent_session_id uuid NOT NULL,
    agent_project text NOT NULL,
    purpose text NOT NULL,
    agent_step_id uuid,
    validation_id uuid,
    version text NOT NULL,
    dirty boolean NOT NULL,
    run_image jsonb NOT NULL,
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
CREATE INDEX ix_execution_records_org_id_agent_session_id_id ON activity.execution_records (org_id, agent_session_id, id);
CREATE INDEX ix_execution_records_org_id_validation_id ON activity.execution_records (org_id, validation_id);
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

CREATE TABLE activity.inferences (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    agent_session_id uuid NOT NULL,
    agent_step_id uuid NOT NULL,
    kind text NOT NULL,
    resolves uuid,
    stance text,
    supports jsonb NOT NULL,
    refutes jsonb NOT NULL,
    CONSTRAINT pk_inferences PRIMARY KEY (id)
);
CREATE INDEX ix_inferences_org_id_agent_session_id_id ON activity.inferences (org_id, agent_session_id, id);
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

CREATE TABLE activity.spend_ledger_counts (
    org_id uuid NOT NULL,
    counter text NOT NULL,
    start timestamptz NOT NULL,
    held bigint NOT NULL,
    spent bigint NOT NULL,
    added bigint NOT NULL,
    CONSTRAINT pk_spend_ledger_counts PRIMARY KEY (org_id, counter, start)
);
ALTER TABLE activity.spend_ledger_counts ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity.spend_ledger_counts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON activity.spend_ledger_counts
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

CREATE TABLE activity.spend_ledger_entries (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    kind text NOT NULL,
    spend_hold_id uuid,
    agent_session_id uuid,
    reference text,
    body jsonb NOT NULL,
    deadline timestamptz,
    CONSTRAINT pk_spend_ledger_entries PRIMARY KEY (id)
);
CREATE INDEX ix_spend_ledger_entries_kind_created_at ON activity.spend_ledger_entries (kind, created_at);
CREATE INDEX ix_spend_ledger_entries_kind_deadline ON activity.spend_ledger_entries (kind, deadline) WHERE (deadline IS NOT NULL);
CREATE INDEX ix_spend_ledger_entries_org_id_agent_session_id_created_at ON activity.spend_ledger_entries (org_id, agent_session_id, created_at);
CREATE INDEX ix_spend_ledger_entries_org_id_kind_created_at ON activity.spend_ledger_entries (org_id, kind, created_at);
CREATE INDEX ix_spend_ledger_entries_org_id_spend_hold_id ON activity.spend_ledger_entries (org_id, spend_hold_id);
CREATE UNIQUE INDEX uq_spend_ledger_entries_org_id_kind_reference ON activity.spend_ledger_entries (org_id, kind, reference);
CREATE UNIQUE INDEX uq_spend_ledger_entries_org_id_kind_spend_hold_id ON activity.spend_ledger_entries (org_id, kind, spend_hold_id);
ALTER TABLE activity.spend_ledger_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity.spend_ledger_entries FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON activity.spend_ledger_entries
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

CREATE TABLE activity.validations (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    agent_session_id uuid NOT NULL,
    agent_project text NOT NULL,
    purpose text NOT NULL,
    version text NOT NULL,
    source text NOT NULL,
    executor text NOT NULL,
    results_sha256 text NOT NULL,
    records jsonb NOT NULL,
    CONSTRAINT pk_validations PRIMARY KEY (id)
);
CREATE INDEX ix_validations_org_id_agent_session_id_id ON activity.validations (org_id, agent_session_id, id);
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

CREATE INDEX ix_spend_budget_holds_created_at ON activity.spend_budget_holds (created_at);

REVOKE UPDATE, DELETE ON activity.execution_records FROM acme_runtime, acme_system;
GRANT SELECT, DELETE ON activity.execution_records TO acme_purge;
REVOKE UPDATE, DELETE ON activity.inferences FROM acme_runtime, acme_system;
GRANT SELECT, DELETE ON activity.inferences TO acme_purge;
REVOKE UPDATE, DELETE ON activity.spend_ledger_entries FROM acme_runtime, acme_system;
REVOKE UPDATE, DELETE ON activity.validations FROM acme_runtime, acme_system;
GRANT SELECT, DELETE ON activity.validations TO acme_purge;
