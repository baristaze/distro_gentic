-- A tenant's labs, station pools, and stations; its daemons' credentials;
-- the line; the leases; and the jobs sent under them. A station's row is
-- the lease store's anchor: a grant writes it on condition that no live
-- lease holds it, and the unique index over a station's leases that have
-- not ended is the second fence. A daemon credential's digest is unique
-- across tenants, since a daemon's call names no tenant (ADR 2006).

CREATE TABLE core.labs (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    name text NOT NULL,
    CONSTRAINT pk_labs PRIMARY KEY (id)
);
CREATE INDEX ix_labs_org_id ON core.labs (org_id);

CREATE TABLE core.station_pools (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    name text NOT NULL,
    job_seconds integer NOT NULL,
    CONSTRAINT pk_station_pools PRIMARY KEY (id)
);
CREATE INDEX ix_station_pools_org_id ON core.station_pools (org_id);

CREATE TABLE core.stations (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    lab_id uuid NOT NULL,
    pool_id uuid NOT NULL,
    name text NOT NULL,
    capabilities jsonb NOT NULL,
    hold_seconds integer NOT NULL,
    token integer NOT NULL,
    lease_id uuid,
    held_until timestamptz,
    CONSTRAINT pk_stations PRIMARY KEY (id)
);
CREATE INDEX ix_stations_org_id_pool_id ON core.stations (org_id, pool_id);
CREATE INDEX ix_stations_org_id_lab_id ON core.stations (org_id, lab_id);

CREATE TABLE core.daemon_credentials (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    lab_id uuid NOT NULL,
    issued_by uuid NOT NULL,
    digest text NOT NULL,
    expires_at timestamptz NOT NULL,
    CONSTRAINT pk_daemon_credentials PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_daemon_credentials_digest ON core.daemon_credentials (digest);
CREATE INDEX ix_daemon_credentials_org_id_lab_id ON core.daemon_credentials (org_id, lab_id);

CREATE TABLE core.station_line_entries (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    session_id uuid NOT NULL,
    pool_id uuid NOT NULL,
    station_id uuid,
    capabilities jsonb NOT NULL,
    project text NOT NULL,
    candidate text NOT NULL,
    procedure text NOT NULL,
    procedure_version text NOT NULL,
    principal jsonb NOT NULL,
    rank double precision NOT NULL,
    state text NOT NULL,
    lease_id uuid,
    settled_at timestamptz,
    CONSTRAINT pk_station_line_entries PRIMARY KEY (id)
);
CREATE INDEX ix_station_line_entries_org_id_pool_id_rank
    ON core.station_line_entries (org_id, pool_id, rank) WHERE state = 'waiting';
CREATE INDEX ix_station_line_entries_org_id_session_id
    ON core.station_line_entries (org_id, session_id) WHERE state = 'waiting';

CREATE TABLE core.station_leases (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    station_id uuid NOT NULL,
    lab_id uuid NOT NULL,
    pool_id uuid NOT NULL,
    entry_id uuid,
    session_id uuid NOT NULL,
    token integer NOT NULL,
    expires_at timestamptz NOT NULL,
    ended_at timestamptz,
    ended text,
    CONSTRAINT pk_station_leases PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_station_leases_org_id_station_id_live
    ON core.station_leases (org_id, station_id) WHERE ended_at IS NULL;

CREATE TABLE core.station_jobs (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    lease_id uuid NOT NULL,
    station_id uuid NOT NULL,
    lab_id uuid NOT NULL,
    session_id uuid NOT NULL,
    token integer NOT NULL,
    project text NOT NULL,
    candidate text NOT NULL,
    procedure text NOT NULL,
    procedure_version text NOT NULL,
    commands jsonb NOT NULL,
    state text NOT NULL,
    claim jsonb,
    run_id uuid,
    finished_at timestamptz,
    CONSTRAINT pk_station_jobs PRIMARY KEY (id)
);
CREATE INDEX ix_station_jobs_org_id ON core.station_jobs (org_id);

-- The second fence: the transaction's own tenant, or the system scope to the
-- system login alone (ADR 0016). The serving logins' grants come from the
-- role's default privileges.

ALTER TABLE core.labs ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.labs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.labs
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

ALTER TABLE core.station_pools ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.station_pools FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.station_pools
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

ALTER TABLE core.stations ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.stations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.stations
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

ALTER TABLE core.daemon_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.daemon_credentials FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.daemon_credentials
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

ALTER TABLE core.station_line_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.station_line_entries FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.station_line_entries
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

ALTER TABLE core.station_leases ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.station_leases FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.station_leases
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

ALTER TABLE core.station_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.station_jobs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.station_jobs
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
