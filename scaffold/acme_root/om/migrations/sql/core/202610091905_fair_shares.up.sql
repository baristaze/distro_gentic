-- Each tenant's fair share of the loops, one row a tenant: the plan tier
-- whose lane its loops run in, whether they run in a lane of their own,
-- and how many of them run at once. The platform's operators write it.

CREATE TABLE core.fair_shares (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    plan_tier text NOT NULL,
    own_lane boolean NOT NULL,
    concurrency integer NOT NULL,
    version integer NOT NULL,
    CONSTRAINT pk_fair_shares PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_fair_shares_org_id ON core.fair_shares (org_id);

-- The second fence: the transaction's own tenant, or the system scope to the
-- system login alone (ADR 0016). The serving logins' grants come from the
-- role's default privileges.

ALTER TABLE core.fair_shares ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.fair_shares FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.fair_shares
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
