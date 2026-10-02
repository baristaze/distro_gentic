-- The model matrix: the platform's versions of it, the benchmark results
-- and retirements its operators record, all of the system scope and no
-- tenant's; and each tenant's pins of its sessions to a version and its own
-- choices of fill, behind the tenant fence.

CREATE TABLE core.matrix_versions (
    id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    number integer NOT NULL,
    roles jsonb NOT NULL,
    rows jsonb NOT NULL,
    status text NOT NULL,
    created_by uuid NOT NULL,
    published_at timestamptz,
    published_by uuid,
    CONSTRAINT pk_matrix_versions PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_matrix_versions_number ON core.matrix_versions (number);

CREATE TABLE core.benchmark_results (
    id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    role text NOT NULL,
    benchmark text NOT NULL,
    passed boolean NOT NULL,
    run text NOT NULL,
    recorded_by uuid NOT NULL,
    CONSTRAINT pk_benchmark_results PRIMARY KEY (id)
);
CREATE INDEX ix_benchmark_results_provider_model_created_at
    ON core.benchmark_results (provider, model, created_at);

CREATE TABLE core.model_retirements (
    id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    recorded_by uuid NOT NULL,
    CONSTRAINT pk_model_retirements PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_model_retirements_provider_model
    ON core.model_retirements (provider, model);

CREATE TABLE core.matrix_pins (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    session_id uuid NOT NULL,
    fill_set_version integer NOT NULL,
    matrix_version integer NOT NULL,
    CONSTRAINT pk_matrix_pins PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_matrix_pins_org_id_session_id_fill_set_version
    ON core.matrix_pins (org_id, session_id, fill_set_version);

CREATE TABLE core.fill_overrides (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    role text NOT NULL,
    fill jsonb NOT NULL,
    CONSTRAINT pk_fill_overrides PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_fill_overrides_org_id_role ON core.fill_overrides (org_id, role);

-- The second fence on the tenant's rows: the transaction's own tenant, or
-- the system scope to the system login alone (ADR 0016). The serving
-- logins' grants come from the role's default privileges.

ALTER TABLE core.matrix_pins ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.matrix_pins FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.matrix_pins
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

ALTER TABLE core.fill_overrides ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.fill_overrides FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.fill_overrides
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

-- A benchmark result is written once. The role's default privileges grant
-- the serving logins every DML statement on a new table; on the results
-- they keep SELECT and INSERT, so no process rewrites what a run showed.

REVOKE UPDATE, DELETE ON core.benchmark_results FROM acme_runtime, acme_system;
