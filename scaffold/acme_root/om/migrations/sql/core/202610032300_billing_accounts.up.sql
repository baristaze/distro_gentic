-- A tenant's billing account: one row per org, under the org's own id. The
-- ledger that draws on it is the activity role's; a hold carries the
-- account as the gate read it, so nothing crosses a role.

CREATE TABLE core.billing_accounts (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    funding text NOT NULL,
    key_ref text,
    plan_id text NOT NULL,
    plan_version integer NOT NULL,
    period_anchor timestamptz NOT NULL,
    credit_line_micros bigint NOT NULL,
    zones jsonb NOT NULL,
    version integer NOT NULL,
    CONSTRAINT pk_billing_accounts PRIMARY KEY (id)
);
CREATE INDEX ix_billing_accounts_org_id ON core.billing_accounts (org_id);

-- The second fence: the transaction's own tenant, or the system scope to the
-- system login alone (ADR 0016). The serving logins' grants come from the
-- role's default privileges.

ALTER TABLE core.billing_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.billing_accounts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.billing_accounts
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
