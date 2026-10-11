-- A session's pin keeps its durability, `cache` or `snapshot`, and the base
-- its workspace starts from; every row there is was pinned a cache on the
-- provider's own image. A project says whether its sessions' workspaces may
-- be kept by snapshots; every project there is lets them. And each snapshot
-- a session keeps, under the snapshot's id: the store that holds it (the
-- platform's bucket, or a host's inside its tenant's wall, by its pool and
-- its host), the reference that store knows it by, its hash and its size,
-- and the digest its host declared. Never its bytes.

ALTER TABLE core.session_workspaces ADD COLUMN durability text NOT NULL DEFAULT 'cache';
ALTER TABLE core.session_workspaces ADD COLUMN base jsonb;
ALTER TABLE core.projects ADD COLUMN workspace_snapshots boolean NOT NULL DEFAULT true;

CREATE TABLE core.workspace_snapshots (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    session_id uuid NOT NULL,
    hash text NOT NULL,
    size bigint NOT NULL,
    pool_id uuid,
    host_id uuid,
    reference text NOT NULL,
    digest text,
    CONSTRAINT pk_workspace_snapshots PRIMARY KEY (id)
);
CREATE INDEX ix_workspace_snapshots_org_id_session_id
    ON core.workspace_snapshots (org_id, session_id);

-- The second fence: the transaction's own tenant, or the system scope to the
-- system login alone (ADR 0016). The serving logins' grants come from the
-- role's default privileges.

ALTER TABLE core.workspace_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.workspace_snapshots FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.workspace_snapshots
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
