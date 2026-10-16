-- The exec relay's parts table, as it was and empty: what it held is gone.

CREATE TABLE core.exec_parts (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    agent_session_id uuid NOT NULL,
    row_id uuid NOT NULL,
    seq integer NOT NULL,
    stream text NOT NULL,
    text bytea,
    sha256 text NOT NULL,
    CONSTRAINT pk_exec_parts PRIMARY KEY (id)
);
CREATE INDEX ix_exec_parts_org_id_agent_session_id ON core.exec_parts (org_id, agent_session_id);
CREATE UNIQUE INDEX uq_exec_parts_org_id_row_id_seq ON core.exec_parts (org_id, row_id, seq);
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
