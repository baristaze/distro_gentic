-- The platform's own tables of the core role, on the engine's: its agent
-- projects and the one each session is set to, its hosts with their pools,
-- enrollment tokens, credentials, and placements, the cloud pool's VMs and
-- erasures, the exec relay's items, parts, and controls, a workspace's
-- bindings, snapshots, and egress allowlists, the agent automations, agent
-- knowledge, and agent playbooks, the connectors, the model matrix, the
-- fair shares, the spend accounts, the retention and validation policies,
-- the validation sessions, and the benchmarks. A tenant's table is fenced
-- to its tenant (ADR 0016); the benchmarks, the matrix's versions and
-- retirements, and the cloud pool's VMs and erasures hold no tenant. The
-- serving logins' grants come from the role's default privileges, less
-- UPDATE and DELETE on what is written once: a session's agent project
-- (ADR 2016) and the benchmarks (ADR 2018). The purge login reaches a
-- session's agent project, within the tenant its transaction names
-- (ADR 1010).

CREATE TABLE core.agent_automation_principals (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    role text NOT NULL,
    granted_by uuid NOT NULL,
    CONSTRAINT pk_agent_automation_principals PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_agent_automation_principals_org_id ON core.agent_automation_principals (org_id);
ALTER TABLE core.agent_automation_principals ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.agent_automation_principals FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.agent_automation_principals
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

CREATE TABLE core.agent_automation_runs (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    agent_automation_id uuid NOT NULL,
    event_id uuid,
    caused_by uuid,
    status text NOT NULL,
    refusal text,
    hop integer NOT NULL,
    agent_session_id uuid,
    opened boolean NOT NULL,
    spend_budget_id uuid,
    reserved_micros bigint NOT NULL,
    event_text text NOT NULL,
    started_at timestamptz,
    closed_at timestamptz,
    work_id uuid,
    outcome text,
    CONSTRAINT pk_agent_automation_runs PRIMARY KEY (id)
);
CREATE INDEX ix_agent_automation_runs_org_id_agent_automation_id_created_at ON core.agent_automation_runs (org_id, agent_automation_id, created_at);
CREATE INDEX ix_agent_automation_runs_org_id_agent_session_id ON core.agent_automation_runs (org_id, agent_session_id);
CREATE INDEX ix_agent_automation_runs_org_id_automation_id_status_created_at ON core.agent_automation_runs (org_id, agent_automation_id, status, created_at);
ALTER TABLE core.agent_automation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.agent_automation_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.agent_automation_runs
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

CREATE TABLE core.agent_automations (
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
    runs_as text NOT NULL,
    CONSTRAINT pk_agent_automations PRIMARY KEY (id)
);
CREATE INDEX ix_agent_automations_org_id ON core.agent_automations (org_id);
ALTER TABLE core.agent_automations ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.agent_automations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.agent_automations
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

CREATE TABLE core.agent_knowledge_entries (
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
    agent_project_id uuid,
    slug text,
    findings jsonb,
    CONSTRAINT pk_agent_knowledge_entries PRIMARY KEY (id)
);
CREATE INDEX ix_agent_knowledge_entries_org_id_slug ON core.agent_knowledge_entries (org_id, slug);
CREATE INDEX ix_agent_knowledge_entries_org_id_status_id ON core.agent_knowledge_entries (org_id, status, id);
ALTER TABLE core.agent_knowledge_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.agent_knowledge_entries FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.agent_knowledge_entries
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

CREATE TABLE core.agent_knowledge_recalls (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    agent_session_id uuid NOT NULL,
    entry_id uuid NOT NULL,
    version integer NOT NULL,
    CONSTRAINT pk_agent_knowledge_recalls PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_agent_knowledge_recalls_org_id_agent_session_id_entry_id ON core.agent_knowledge_recalls (org_id, agent_session_id, entry_id);
ALTER TABLE core.agent_knowledge_recalls ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.agent_knowledge_recalls FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.agent_knowledge_recalls
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

CREATE TABLE core.agent_playbook_invocations (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    agent_session_id uuid NOT NULL,
    agent_playbook_id uuid NOT NULL,
    name text NOT NULL,
    version integer NOT NULL,
    invoked_by uuid NOT NULL,
    pinned boolean DEFAULT false NOT NULL,
    CONSTRAINT pk_agent_playbook_invocations PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_agent_playbook_invocations_org_id_session_id_agent_playbook ON core.agent_playbook_invocations (org_id, agent_session_id, agent_playbook_id);
ALTER TABLE core.agent_playbook_invocations ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.agent_playbook_invocations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.agent_playbook_invocations
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

CREATE TABLE core.agent_playbook_pins (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    kind text NOT NULL,
    agent_project_id uuid,
    agent_playbook_id uuid NOT NULL,
    name text NOT NULL,
    version integer NOT NULL,
    CONSTRAINT pk_agent_playbook_pins PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_agent_playbook_pins_org_id_kind_agent_project_id ON core.agent_playbook_pins (org_id, kind, agent_project_id) NULLS NOT DISTINCT;
ALTER TABLE core.agent_playbook_pins ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.agent_playbook_pins FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.agent_playbook_pins
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

CREATE TABLE core.agent_playbooks (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    name text NOT NULL,
    created_at timestamptz NOT NULL,
    version integer NOT NULL,
    description text NOT NULL,
    body text NOT NULL,
    gates jsonb NOT NULL,
    published_by uuid NOT NULL,
    findings jsonb,
    CONSTRAINT pk_agent_playbooks PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_agent_playbooks_org_id_name_version ON core.agent_playbooks (org_id, name, version);
ALTER TABLE core.agent_playbooks ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.agent_playbooks FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.agent_playbooks
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

CREATE TABLE core.agent_projects (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    name text NOT NULL,
    repository jsonb NOT NULL,
    workspace_snapshots boolean DEFAULT true NOT NULL,
    agent_workspace_base jsonb,
    CONSTRAINT pk_agent_projects PRIMARY KEY (id)
);
CREATE INDEX ix_agent_projects_org_id ON core.agent_projects (org_id);
ALTER TABLE core.agent_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.agent_projects FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.agent_projects
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

CREATE TABLE core.agent_session_connectors (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    connectors jsonb NOT NULL,
    CONSTRAINT pk_agent_session_connectors PRIMARY KEY (id)
);
CREATE INDEX ix_agent_session_connectors_org_id ON core.agent_session_connectors (org_id);
ALTER TABLE core.agent_session_connectors ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.agent_session_connectors FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.agent_session_connectors
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

CREATE TABLE core.agent_session_placements (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    agent_session_id uuid NOT NULL,
    pool_id uuid,
    version integer NOT NULL,
    CONSTRAINT pk_agent_session_placements PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_agent_session_placements_org_id_agent_session_id ON core.agent_session_placements (org_id, agent_session_id);
ALTER TABLE core.agent_session_placements ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.agent_session_placements FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.agent_session_placements
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

CREATE TABLE core.agent_session_projects (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    agent_project_id uuid NOT NULL,
    CONSTRAINT pk_agent_session_projects PRIMARY KEY (id)
);
CREATE INDEX ix_agent_session_projects_org_id ON core.agent_session_projects (org_id);
ALTER TABLE core.agent_session_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.agent_session_projects FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.agent_session_projects
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

CREATE TABLE core.agent_session_retention (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    agent_session_id uuid NOT NULL,
    agent_project_id uuid,
    policy jsonb NOT NULL,
    policy_version integer NOT NULL,
    at_rest boolean NOT NULL,
    content_expires_at timestamptz,
    shape_expires_at timestamptz,
    content_expired_at timestamptz,
    destruction jsonb,
    shape_expired_at timestamptz,
    next_attempt_at timestamptz,
    version integer NOT NULL,
    CONSTRAINT pk_agent_session_retention PRIMARY KEY (id)
);
CREATE INDEX ix_agent_session_retention_content_expires_at ON core.agent_session_retention (content_expires_at) WHERE ((content_expires_at IS NOT NULL) AND (content_expired_at IS NULL));
CREATE INDEX ix_agent_session_retention_org_id_policy_version ON core.agent_session_retention (org_id, policy_version);
CREATE INDEX ix_agent_session_retention_shape_expires_at ON core.agent_session_retention (shape_expires_at) WHERE ((shape_expires_at IS NOT NULL) AND (shape_expired_at IS NULL));
CREATE UNIQUE INDEX uq_agent_session_retention_org_id_agent_session_id ON core.agent_session_retention (org_id, agent_session_id);
ALTER TABLE core.agent_session_retention ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.agent_session_retention FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.agent_session_retention
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

CREATE TABLE core.agent_session_workspaces (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    agent_project_id uuid,
    level text NOT NULL,
    limits jsonb NOT NULL,
    egress text NOT NULL,
    rules jsonb NOT NULL,
    egress_source text NOT NULL,
    branch text NOT NULL,
    branch_seen boolean NOT NULL,
    snapshot_ref text,
    version integer NOT NULL,
    push_digest text,
    push_expires_at timestamptz,
    notices jsonb NOT NULL,
    durability text DEFAULT 'cache'::text NOT NULL,
    base jsonb,
    CONSTRAINT pk_agent_session_workspaces PRIMARY KEY (id)
);
CREATE INDEX ix_agent_session_workspaces_org_id ON core.agent_session_workspaces (org_id);
ALTER TABLE core.agent_session_workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.agent_session_workspaces FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.agent_session_workspaces
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

CREATE TABLE core.agent_workspace_bindings (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    agent_session_id uuid NOT NULL,
    host_id uuid NOT NULL,
    host_name text NOT NULL,
    location text NOT NULL,
    version integer NOT NULL,
    instance_of uuid,
    CONSTRAINT pk_agent_workspace_bindings PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_agent_workspace_bindings_org_id_agent_session_id ON core.agent_workspace_bindings (org_id, agent_session_id);
ALTER TABLE core.agent_workspace_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.agent_workspace_bindings FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.agent_workspace_bindings
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

CREATE TABLE core.agent_workspace_snapshots (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    agent_session_id uuid NOT NULL,
    hash text NOT NULL,
    size bigint NOT NULL,
    pool_id uuid,
    host_id uuid,
    reference text NOT NULL,
    digest text,
    vm boolean DEFAULT false NOT NULL,
    CONSTRAINT pk_agent_workspace_snapshots PRIMARY KEY (id)
);
CREATE INDEX ix_agent_workspace_snapshots_org_id_agent_session_id ON core.agent_workspace_snapshots (org_id, agent_session_id);
ALTER TABLE core.agent_workspace_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.agent_workspace_snapshots FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.agent_workspace_snapshots
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

CREATE TABLE core.benchmark_results (
    id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    role text NOT NULL,
    benchmark text NOT NULL,
    passed boolean NOT NULL,
    run text NOT NULL,
    recorded_by uuid NOT NULL,
    CONSTRAINT pk_benchmark_results PRIMARY KEY (id)
);
CREATE INDEX ix_benchmark_results_provider_model_created_at ON core.benchmark_results (provider, model, created_at);

CREATE TABLE core.benchmarks (
    id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    scenario text NOT NULL,
    candidate jsonb NOT NULL,
    baseline jsonb NOT NULL,
    trials jsonb NOT NULL,
    candidate_result jsonb NOT NULL,
    baseline_result jsonb NOT NULL,
    regressed boolean NOT NULL,
    recorded_by uuid NOT NULL,
    CONSTRAINT pk_benchmarks PRIMARY KEY (id)
);
CREATE INDEX ix_benchmarks_scenario_created_at ON core.benchmarks (scenario, created_at);

CREATE TABLE core.connectors (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    name text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    summary text NOT NULL,
    place text NOT NULL,
    url text,
    credential_header text NOT NULL,
    credential_scheme text NOT NULL,
    secret text,
    host_server text,
    tools jsonb NOT NULL,
    review integer NOT NULL,
    reviewed_by uuid,
    attachments jsonb NOT NULL,
    version integer NOT NULL,
    CONSTRAINT pk_connectors PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_connectors_org_id_name ON core.connectors (org_id, name);
ALTER TABLE core.connectors ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.connectors FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.connectors
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

CREATE TABLE core.content_grants (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    identity_id uuid NOT NULL,
    expires_at timestamptz NOT NULL,
    CONSTRAINT pk_content_grants PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_content_grants_org_id_identity_id ON core.content_grants (org_id, identity_id);
ALTER TABLE core.content_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.content_grants FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.content_grants
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

CREATE TABLE core.egress_allowlists (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    agent_project_id uuid NOT NULL,
    rules jsonb NOT NULL,
    open boolean NOT NULL,
    reason text,
    version integer NOT NULL,
    CONSTRAINT pk_egress_allowlists PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_egress_allowlists_org_id_agent_project_id ON core.egress_allowlists (org_id, agent_project_id);
ALTER TABLE core.egress_allowlists ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.egress_allowlists FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.egress_allowlists
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

CREATE TABLE core.exec_controls (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    agent_session_id uuid NOT NULL,
    item_id uuid NOT NULL,
    host_id uuid NOT NULL,
    kind text NOT NULL,
    CONSTRAINT pk_exec_controls PRIMARY KEY (id)
);
CREATE INDEX ix_exec_controls_org_id_agent_session_id ON core.exec_controls (org_id, agent_session_id);
CREATE INDEX ix_exec_controls_org_id_host_id_created_at ON core.exec_controls (org_id, host_id, created_at);
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

CREATE TABLE core.exec_items (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    agent_session_id uuid NOT NULL,
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
CREATE INDEX ix_exec_items_lease_expires_at_running ON core.exec_items (lease_expires_at) WHERE (state = 'running'::text);
CREATE INDEX ix_exec_items_org_id_agent_session_id_key ON core.exec_items (org_id, agent_session_id, key);
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

CREATE TABLE core.fair_shares (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    plan_tier text NOT NULL,
    own_lane boolean NOT NULL,
    concurrency integer DEFAULT 8 NOT NULL,
    version integer NOT NULL,
    cap_carried boolean DEFAULT false NOT NULL,
    CONSTRAINT pk_fair_shares PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_fair_shares_org_id ON core.fair_shares (org_id);
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

CREATE TABLE core.fill_overrides (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    role text NOT NULL,
    fill jsonb NOT NULL,
    CONSTRAINT pk_fill_overrides PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_fill_overrides_org_id_role ON core.fill_overrides (org_id, role);
ALTER TABLE core.fill_overrides ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.fill_overrides FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.fill_overrides
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

CREATE TABLE core.host_credentials (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    host_id uuid NOT NULL,
    digest text NOT NULL,
    expires_at timestamptz NOT NULL,
    rotated_at timestamptz,
    CONSTRAINT pk_host_credentials PRIMARY KEY (id)
);
CREATE INDEX ix_host_credentials_org_id_host_id ON core.host_credentials (org_id, host_id);
CREATE UNIQUE INDEX uq_host_credentials_digest ON core.host_credentials (digest);
ALTER TABLE core.host_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.host_credentials FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.host_credentials
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

CREATE TABLE core.host_enrollment_tokens (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    pool_id uuid NOT NULL,
    digest text NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    revoked_by uuid,
    kind text DEFAULT 'host'::text NOT NULL,
    CONSTRAINT pk_host_enrollment_tokens PRIMARY KEY (id)
);
CREATE INDEX ix_host_enrollment_tokens_org_id ON core.host_enrollment_tokens (org_id);
CREATE UNIQUE INDEX uq_host_enrollment_tokens_digest ON core.host_enrollment_tokens (digest);
ALTER TABLE core.host_enrollment_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.host_enrollment_tokens FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.host_enrollment_tokens
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

CREATE TABLE core.host_pools (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    name text NOT NULL,
    region text NOT NULL,
    labels jsonb NOT NULL,
    agent_session_id uuid,
    CONSTRAINT pk_host_pools PRIMARY KEY (id)
);
CREATE INDEX ix_host_pools_org_id ON core.host_pools (org_id);
ALTER TABLE core.host_pools ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.host_pools FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.host_pools
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

CREATE TABLE core.hosts (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    pool_id uuid NOT NULL,
    name text NOT NULL,
    enrolled_with uuid NOT NULL,
    advertisement jsonb,
    exec_version integer,
    last_seen_at timestamptz NOT NULL,
    revoked_at timestamptz,
    revoked_by uuid,
    kind text DEFAULT 'host'::text NOT NULL,
    agent_session_id uuid,
    CONSTRAINT pk_hosts PRIMARY KEY (id)
);
CREATE INDEX ix_hosts_org_id_pool_id ON core.hosts (org_id, pool_id);
ALTER TABLE core.hosts ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.hosts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.hosts
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

CREATE TABLE core.identity_links (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    integration text NOT NULL,
    external_id text NOT NULL,
    user_id uuid NOT NULL,
    created_by uuid NOT NULL,
    CONSTRAINT pk_identity_links PRIMARY KEY (id)
);
CREATE INDEX ix_identity_links_org_id_user_id ON core.identity_links (org_id, user_id);
CREATE UNIQUE INDEX uq_identity_links_org_id_integration_external_id ON core.identity_links (org_id, integration, external_id);
ALTER TABLE core.identity_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.identity_links FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.identity_links
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

CREATE TABLE core.installations (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    integration text NOT NULL,
    installation text NOT NULL,
    created_by uuid NOT NULL,
    CONSTRAINT pk_installations PRIMARY KEY (id)
);
CREATE INDEX ix_installations_org_id ON core.installations (org_id);
CREATE UNIQUE INDEX uq_installations_integration_installation ON core.installations (integration, installation);
ALTER TABLE core.installations ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.installations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.installations
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

CREATE TABLE core.matrix_pins (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    agent_session_id uuid NOT NULL,
    fill_set_version integer NOT NULL,
    matrix_version integer NOT NULL,
    CONSTRAINT pk_matrix_pins PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_matrix_pins_org_id_agent_session_id_fill_set_version ON core.matrix_pins (org_id, agent_session_id, fill_set_version);
ALTER TABLE core.matrix_pins ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.matrix_pins FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.matrix_pins
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

CREATE TABLE core.matrix_versions (
    id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    number integer NOT NULL,
    roles jsonb NOT NULL,
    rows jsonb NOT NULL,
    status text NOT NULL,
    created_by uuid NOT NULL,
    published_at timestamptz,
    published_by uuid,
    CONSTRAINT pk_matrix_versions PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_matrix_versions_number ON core.matrix_versions (number);

CREATE TABLE core.model_retirements (
    id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    recorded_by uuid NOT NULL,
    CONSTRAINT pk_model_retirements PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_model_retirements_provider_model ON core.model_retirements (provider, model);

CREATE TABLE core.park_alerts (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    recipient uuid NOT NULL,
    agent_session_id uuid NOT NULL,
    park_step uuid NOT NULL,
    reason text NOT NULL,
    unlock text NOT NULL,
    action text NOT NULL,
    link text NOT NULL,
    channel text NOT NULL,
    address text NOT NULL,
    provenance text,
    text text NOT NULL,
    read_at timestamptz,
    CONSTRAINT pk_park_alerts PRIMARY KEY (id)
);
CREATE INDEX ix_park_alerts_org_id_agent_session_id ON core.park_alerts (org_id, agent_session_id);
CREATE INDEX ix_park_alerts_org_id_recipient_created_at ON core.park_alerts (org_id, recipient, created_at);
ALTER TABLE core.park_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.park_alerts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.park_alerts
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

CREATE TABLE core.platform_acts (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    integration text NOT NULL,
    ref text NOT NULL,
    agent_session_id uuid NOT NULL,
    CONSTRAINT pk_platform_acts PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_platform_acts_org_id_integration_ref ON core.platform_acts (org_id, integration, ref);
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

CREATE TABLE core.pool_erasures (
    id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    tenant_id uuid NOT NULL,
    agent_session_id uuid NOT NULL,
    CONSTRAINT pk_pool_erasures PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_pool_erasures_tenant_id_agent_session_id ON core.pool_erasures (tenant_id, agent_session_id);

CREATE TABLE core.pool_vms (
    id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    name text NOT NULL,
    egress_open boolean NOT NULL,
    tenant_id uuid,
    agent_session_id uuid,
    pool_id uuid,
    bound_by uuid,
    host_id uuid,
    key_digest text,
    restored_from uuid,
    started_at timestamptz,
    bound_at timestamptz,
    sealed_at timestamptz,
    CONSTRAINT pk_pool_vms PRIMARY KEY (id)
);
CREATE INDEX ix_pool_vms_tenant_id_agent_session_id ON core.pool_vms (tenant_id, agent_session_id);
CREATE UNIQUE INDEX uq_pool_vms_key_digest ON core.pool_vms (key_digest);
CREATE UNIQUE INDEX uq_pool_vms_name ON core.pool_vms (name);

CREATE TABLE core.provider_keys (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    provider text NOT NULL,
    status text NOT NULL,
    last_used_at timestamptz,
    version integer NOT NULL,
    CONSTRAINT pk_provider_keys PRIMARY KEY (id)
);
CREATE INDEX ix_provider_keys_org_id_created_at ON core.provider_keys (org_id, created_at);
CREATE UNIQUE INDEX uq_provider_keys_org_id_provider_live ON core.provider_keys (org_id, provider) WHERE (status = 'live'::text);
ALTER TABLE core.provider_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.provider_keys FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.provider_keys
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

CREATE TABLE core.repository_credentials (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    version integer NOT NULL,
    CONSTRAINT pk_repository_credentials PRIMARY KEY (id)
);
CREATE INDEX ix_repository_credentials_org_id ON core.repository_credentials (org_id);
ALTER TABLE core.repository_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.repository_credentials FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.repository_credentials
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

CREATE TABLE core.retention_policies (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    policy jsonb NOT NULL,
    agent_projects jsonb NOT NULL,
    version integer NOT NULL,
    CONSTRAINT pk_retention_policies PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_retention_policies_org_id ON core.retention_policies (org_id);
ALTER TABLE core.retention_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.retention_policies FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.retention_policies
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

CREATE TABLE core.secret_declarations (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    name text NOT NULL,
    variable text NOT NULL,
    owner_kind text NOT NULL,
    owner_id uuid NOT NULL,
    scope text NOT NULL,
    store text NOT NULL,
    CONSTRAINT pk_secret_declarations PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_secret_declarations_org_id_name_owner ON core.secret_declarations (org_id, name, owner_kind, owner_id);
ALTER TABLE core.secret_declarations ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.secret_declarations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.secret_declarations
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

CREATE TABLE core.spend_accounts (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    funding text NOT NULL,
    key_ref text,
    unit_plan_id text NOT NULL,
    unit_plan_version integer NOT NULL,
    period_anchor timestamptz NOT NULL,
    credit_line_micros bigint NOT NULL,
    zones jsonb NOT NULL,
    version integer NOT NULL,
    CONSTRAINT pk_spend_accounts PRIMARY KEY (id)
);
CREATE INDEX ix_spend_accounts_org_id ON core.spend_accounts (org_id);
ALTER TABLE core.spend_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.spend_accounts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.spend_accounts
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

CREATE TABLE core.validation_policies (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    agent_project text NOT NULL,
    checks jsonb NOT NULL,
    requirements jsonb NOT NULL,
    protected jsonb NOT NULL,
    version integer NOT NULL,
    CONSTRAINT pk_validation_policies PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_validation_policies_org_id_agent_project ON core.validation_policies (org_id, agent_project);
ALTER TABLE core.validation_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.validation_policies FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.validation_policies
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

CREATE TABLE core.validation_sessions (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    check_name text NOT NULL,
    status text NOT NULL,
    run_id uuid,
    finished_at timestamptz,
    version integer NOT NULL,
    agent_project_id uuid NOT NULL,
    head text NOT NULL,
    base text NOT NULL,
    refusal text,
    key_id uuid,
    CONSTRAINT pk_validation_sessions PRIMARY KEY (id)
);
CREATE INDEX ix_validation_sessions_org_id ON core.validation_sessions (org_id);
ALTER TABLE core.validation_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.validation_sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.validation_sessions
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

CREATE TABLE core.work_bindings (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    agent_session_id uuid NOT NULL,
    kind text NOT NULL,
    handle text NOT NULL,
    CONSTRAINT pk_work_bindings PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_work_bindings_org_id_kind_handle ON core.work_bindings (org_id, kind, handle);
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

REVOKE UPDATE, DELETE ON core.agent_session_projects FROM acme_runtime, acme_system;
GRANT SELECT, DELETE ON core.agent_session_projects TO acme_purge;
REVOKE UPDATE, DELETE ON core.benchmark_results FROM acme_runtime, acme_system;
REVOKE UPDATE, DELETE ON core.benchmarks FROM acme_runtime, acme_system;
