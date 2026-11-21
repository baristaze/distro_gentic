-- Takes the pool's archive records back out, and brings back the erasures
-- of disks it owed and the flag that named a disk among a session's
-- snapshots.

ALTER TABLE core.agent_workspace_snapshots ADD COLUMN vm boolean DEFAULT false NOT NULL;

DROP TABLE core.pool_archives;

CREATE TABLE core.pool_erasures (
    id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    tenant_id uuid NOT NULL,
    agent_session_id uuid NOT NULL,
    CONSTRAINT pk_pool_erasures PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_pool_erasures_tenant_id_agent_session_id ON core.pool_erasures (tenant_id, agent_session_id);
