-- The one ledger: every hold, settlement, charge, credit, grant, raise, and
-- approval, one row each, written once; and one count per counter and
-- period, which an entry moves under the count's lock in the transaction
-- that writes it.

CREATE TABLE activity.ledger_counts (
    org_id uuid NOT NULL,
    counter text NOT NULL,
    start timestamptz NOT NULL,
    held bigint NOT NULL,
    spent bigint NOT NULL,
    added bigint NOT NULL,
    CONSTRAINT pk_ledger_counts PRIMARY KEY (org_id, counter, start)
);

CREATE TABLE activity.ledger_entries (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    kind text NOT NULL,
    hold_id uuid,
    session_id uuid,
    reference text,
    body jsonb NOT NULL,
    CONSTRAINT pk_ledger_entries PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_ledger_entries_org_id_kind_hold_id ON activity.ledger_entries (org_id, kind, hold_id);
CREATE UNIQUE INDEX uq_ledger_entries_org_id_kind_reference ON activity.ledger_entries (org_id, kind, reference);
CREATE INDEX ix_ledger_entries_org_id_hold_id ON activity.ledger_entries (org_id, hold_id);
CREATE INDEX ix_ledger_entries_org_id_session_id_created_at ON activity.ledger_entries (org_id, session_id, created_at);
CREATE INDEX ix_ledger_entries_org_id_kind_created_at ON activity.ledger_entries (org_id, kind, created_at);

-- The second fence: the transaction's own tenant, or the system scope to the
-- system login alone (ADR 0016).

ALTER TABLE activity.ledger_counts ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity.ledger_counts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON activity.ledger_counts
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

ALTER TABLE activity.ledger_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity.ledger_entries FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON activity.ledger_entries
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

-- An entry is written once. The role's default privileges grant the serving
-- logins every DML statement on a new table; on the entries they keep SELECT
-- and INSERT, so no statement a process sends rewrites or removes what the
-- ledger holds.

REVOKE UPDATE, DELETE ON activity.ledger_entries FROM acme_runtime, acme_system;
