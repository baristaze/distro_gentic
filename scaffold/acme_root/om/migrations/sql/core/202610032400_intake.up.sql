-- The rows of intake, automations, playbooks, and knowledge. Each names
-- its tenant and sits behind the tenant fence.

-- An outside account mapped to a user of the tenant, one row an account.
CREATE TABLE core.account_links (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    integration text NOT NULL,
    external_id text NOT NULL,
    user_id uuid NOT NULL,
    created_by uuid NOT NULL,
    CONSTRAINT pk_account_links PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_account_links_org_id_integration_external_id ON core.account_links (org_id, integration, external_id);

-- A pull request or a branch that is a session's work, one session a handle.
CREATE TABLE core.work_bindings (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    session_id uuid NOT NULL,
    kind text NOT NULL,
    handle text NOT NULL,
    CONSTRAINT pk_work_bindings PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_work_bindings_org_id_kind_handle ON core.work_bindings (org_id, kind, handle);

-- An act a session made through the platform's account, by the name of what it made.
CREATE TABLE core.platform_acts (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    integration text NOT NULL,
    ref text NOT NULL,
    session_id uuid NOT NULL,
    CONSTRAINT pk_platform_acts PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_platform_acts_org_id_integration_ref ON core.platform_acts (org_id, integration, ref);

-- A tenant's automations: a trigger, an action, and limits of its own.
CREATE TABLE core.automations (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    name text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    trigger jsonb NOT NULL,
    action jsonb NOT NULL,
    limits jsonb NOT NULL,
    own_events boolean NOT NULL,
    enabled boolean NOT NULL,
    CONSTRAINT pk_automations PRIMARY KEY (id)
);
CREATE INDEX ix_automations_org_id ON core.automations (org_id);

-- The record of every firing, whatever became of it.
CREATE TABLE core.automation_runs (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    automation_id uuid NOT NULL,
    event_id uuid,
    caused_by uuid,
    status text NOT NULL,
    refusal text,
    hop integer NOT NULL,
    session_id uuid,
    opened boolean NOT NULL,
    budget_id uuid,
    reserved_micros bigint NOT NULL,
    event_text text NOT NULL,
    started_at timestamptz,
    closed_at timestamptz,
    CONSTRAINT pk_automation_runs PRIMARY KEY (id)
);
CREATE INDEX ix_automation_runs_org_id_automation_id_created_at ON core.automation_runs (org_id, automation_id, created_at);
CREATE INDEX ix_automation_runs_org_id_session_id ON core.automation_runs (org_id, session_id);

-- Every published version of a playbook, written once.
CREATE TABLE core.playbooks (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    name text NOT NULL,
    created_at timestamptz NOT NULL,
    version integer NOT NULL,
    description text NOT NULL,
    body text NOT NULL,
    gates jsonb NOT NULL,
    published_by uuid NOT NULL,
    CONSTRAINT pk_playbooks PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_playbooks_org_id_name_version ON core.playbooks (org_id, name, version);

-- The playbook versions each session invoked, whose gates hold there.
CREATE TABLE core.playbook_invocations (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    session_id uuid NOT NULL,
    playbook_id uuid NOT NULL,
    name text NOT NULL,
    version integer NOT NULL,
    invoked_by uuid NOT NULL,
    CONSTRAINT pk_playbook_invocations PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_playbook_invocations_org_id_session_id_playbook_id ON core.playbook_invocations (org_id, session_id, playbook_id);

-- A tenant's knowledge: suggested, reviewed, or rejected.
CREATE TABLE core.knowledge_entries (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    trigger jsonb NOT NULL,
    text text NOT NULL,
    status text NOT NULL,
    suggested_by uuid,
    reviewed_by uuid,
    title text NOT NULL,
    version integer NOT NULL,
    CONSTRAINT pk_knowledge_entries PRIMARY KEY (id)
);
CREATE INDEX ix_knowledge_entries_org_id_status_id ON core.knowledge_entries (org_id, status, id);

-- The second fence on each: the transaction's own tenant, or the system
-- scope to the system login alone (ADR 0016). The serving logins' grants
-- come from the role's default privileges.

ALTER TABLE core.account_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.account_links FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.account_links
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

ALTER TABLE core.work_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.work_bindings FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.work_bindings
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

ALTER TABLE core.platform_acts ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.platform_acts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.platform_acts
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

ALTER TABLE core.automations ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.automations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.automations
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

ALTER TABLE core.automation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.automation_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.automation_runs
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

ALTER TABLE core.playbooks ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.playbooks FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.playbooks
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

ALTER TABLE core.playbook_invocations ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.playbook_invocations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.playbook_invocations
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

ALTER TABLE core.knowledge_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.knowledge_entries FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.knowledge_entries
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
