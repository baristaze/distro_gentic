-- The versions a tenant pinned to its kinds as their manuals: one row a
-- kind in a project, or in none for the tenant's, the two never confused.
CREATE TABLE core.playbook_pins (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    kind text NOT NULL,
    project_id uuid,
    playbook_id uuid NOT NULL,
    name text NOT NULL,
    version integer NOT NULL,
    CONSTRAINT pk_playbook_pins PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_playbook_pins_org_id_kind_project_id ON core.playbook_pins (org_id, kind, project_id) NULLS NOT DISTINCT;

ALTER TABLE core.playbook_pins ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.playbook_pins FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.playbook_pins
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

-- Which invocation of a session is the manual it was made with. Every row
-- before was a principal's, its brief a message, and so is every row the
-- release before inserts for the minutes of the roll: it names no column.
ALTER TABLE core.playbook_invocations ADD COLUMN pinned boolean NOT NULL DEFAULT false;
