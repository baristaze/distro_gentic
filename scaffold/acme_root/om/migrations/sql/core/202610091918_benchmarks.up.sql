-- What the benchmark job showed of a candidate against its baseline: the
-- platform's own record, of the system scope and no tenant's.

CREATE TABLE core.benchmarks (
    id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    scenario text NOT NULL,
    candidate jsonb NOT NULL,
    baseline jsonb NOT NULL,
    trials jsonb NOT NULL,
    candidate_result jsonb NOT NULL,
    baseline_result jsonb NOT NULL,
    regressed boolean NOT NULL,
    recorded_by uuid NOT NULL,
    CONSTRAINT pk_benchmarks PRIMARY KEY (id)
);
CREATE INDEX ix_benchmarks_scenario_created_at ON core.benchmarks (scenario, created_at);

-- A benchmark is written once. The role's default privileges grant the
-- serving logins every DML statement on a new table; on this one they keep
-- SELECT and INSERT, so no process rewrites what a run showed.

REVOKE UPDATE, DELETE ON core.benchmarks FROM acme_runtime, acme_system;
