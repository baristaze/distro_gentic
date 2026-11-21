-- The cloud pool keeps no disk of any VM: a session's workspace files are
-- archived in the snapshots bucket, and the pool records each session that
-- keeps archives, with the latest moment it was active, so its sweep
-- removes them once the session is idle. The erasures of disks it owed, and
-- the flag that named a disk among a session's snapshots, go.

DROP TABLE core.pool_erasures;

CREATE TABLE core.pool_archives (
    id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    tenant_id uuid NOT NULL,
    agent_session_id uuid NOT NULL,
    kept_at timestamptz NOT NULL,
    CONSTRAINT pk_pool_archives PRIMARY KEY (id)
);
CREATE INDEX ix_pool_archives_kept_at ON core.pool_archives (kept_at);
CREATE UNIQUE INDEX uq_pool_archives_tenant_id_agent_session_id ON core.pool_archives (tenant_id, agent_session_id);

ALTER TABLE core.agent_workspace_snapshots DROP COLUMN vm;
