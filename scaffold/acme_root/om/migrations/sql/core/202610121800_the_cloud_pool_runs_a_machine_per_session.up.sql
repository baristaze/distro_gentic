-- The cloud pool runs a machine per session. Each machine it starts is a
-- row of the platform's own, of the system scope, since a warm machine
-- serves no tenant until a session claims it: its name in the machines'
-- backend, its egress, and, once claimed, the tenant, the session, the
-- session's pool of one, and the person its work is for; the digest of the
-- one-use key it was handed, until its host trades it; and the host that
-- did. A session's pool of one names its session, and so does each host
-- enrolled into one. A snapshot a session keeps may live in the machines'
-- store; every snapshot there is lives elsewhere. The erasures the pool owes
-- are its own rows too, one per session whose disks are to go, until its
-- sweep has destroyed them.

ALTER TABLE core.host_pools ADD COLUMN session_id uuid;
ALTER TABLE core.hosts ADD COLUMN session_id uuid;
ALTER TABLE core.workspace_snapshots ADD COLUMN machine boolean NOT NULL DEFAULT false;

CREATE TABLE core.pool_machines (
    id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    name text NOT NULL,
    egress_open boolean NOT NULL,
    tenant_id uuid,
    session_id uuid,
    pool_id uuid,
    bound_by uuid,
    host_id uuid,
    key_digest text,
    restored_from uuid,
    started_at timestamptz,
    bound_at timestamptz,
    sealed_at timestamptz,
    CONSTRAINT pk_pool_machines PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_pool_machines_name ON core.pool_machines (name);
CREATE UNIQUE INDEX uq_pool_machines_key_digest ON core.pool_machines (key_digest);
CREATE INDEX ix_pool_machines_tenant_id_session_id
    ON core.pool_machines (tenant_id, session_id);

CREATE TABLE core.pool_erasures (
    id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    tenant_id uuid NOT NULL,
    session_id uuid NOT NULL,
    CONSTRAINT pk_pool_erasures PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_pool_erasures_tenant_id_session_id
    ON core.pool_erasures (tenant_id, session_id);
