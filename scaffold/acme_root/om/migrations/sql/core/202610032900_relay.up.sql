-- The relay: each operation a session's calls send into a customer's wall,
-- with how it ended; the parts of its output; the control messages for the
-- host that holds it; and the host that holds each session's workspace.
-- What an item runs and prints is sealed under its session's key (ADR 2004).

CREATE TABLE core.exec_items (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    session_id uuid NOT NULL,
    key uuid NOT NULL,
    operation text NOT NULL,
    effect text NOT NULL,
    host_id uuid NOT NULL,
    location text NOT NULL,
    spec jsonb NOT NULL,
    deadline timestamptz NOT NULL,
    epoch integer,
    request bytea NOT NULL,
    state text NOT NULL,
    dispatch integer NOT NULL,
    row_id uuid NOT NULL,
    claim jsonb,
    lease_expires_at timestamptz,
    outcome jsonb,
    output bytea,
    result_sha256 text,
    settled_at timestamptz,
    version integer NOT NULL,
    CONSTRAINT pk_exec_items PRIMARY KEY (id)
);
CREATE INDEX ix_exec_items_org_id_session_id_key ON core.exec_items (org_id, session_id, key);
CREATE INDEX ix_exec_items_lease_expires_at_running
    ON core.exec_items (lease_expires_at) WHERE state = 'running';

CREATE TABLE core.exec_parts (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    session_id uuid NOT NULL,
    row_id uuid NOT NULL,
    seq integer NOT NULL,
    stream text NOT NULL,
    text bytea,
    sha256 text NOT NULL,
    CONSTRAINT pk_exec_parts PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_exec_parts_org_id_row_id_seq ON core.exec_parts (org_id, row_id, seq);
CREATE INDEX ix_exec_parts_org_id_session_id ON core.exec_parts (org_id, session_id);

CREATE TABLE core.exec_controls (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    session_id uuid NOT NULL,
    item_id uuid NOT NULL,
    host_id uuid NOT NULL,
    kind text NOT NULL,
    CONSTRAINT pk_exec_controls PRIMARY KEY (id)
);
CREATE INDEX ix_exec_controls_org_id_host_id_created_at
    ON core.exec_controls (org_id, host_id, created_at);
CREATE INDEX ix_exec_controls_org_id_session_id ON core.exec_controls (org_id, session_id);

CREATE TABLE core.workspace_bindings (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    session_id uuid NOT NULL,
    host_id uuid NOT NULL,
    host_name text NOT NULL,
    location text NOT NULL,
    version integer NOT NULL,
    CONSTRAINT pk_workspace_bindings PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_workspace_bindings_org_id_session_id
    ON core.workspace_bindings (org_id, session_id);

-- The second fence: the transaction's own tenant, or the system scope to the
-- system login alone (ADR 0016). The serving logins' grants come from the
-- role's default privileges.

ALTER TABLE core.exec_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.exec_items FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.exec_items
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

ALTER TABLE core.exec_parts ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.exec_parts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.exec_parts
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

ALTER TABLE core.exec_controls ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.exec_controls FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.exec_controls
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

ALTER TABLE core.workspace_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.workspace_bindings FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.workspace_bindings
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
