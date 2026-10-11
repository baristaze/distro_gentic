-- What the lever checks read in each playbook version and knowledge entry,
-- kept with the version they read. A row an earlier release wrote, and one
-- the release before inserts for the minutes of the roll, was never read by
-- them: its findings are null, never checked, which is not an empty list,
-- checked and clean.

ALTER TABLE core.playbooks ADD COLUMN findings jsonb;
ALTER TABLE core.knowledge_entries ADD COLUMN findings jsonb;

-- The entry versions each session recalled, which a reading of the sessions
-- that stalled names.
CREATE TABLE core.knowledge_recalls (
    id uuid NOT NULL,
    org_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    session_id uuid NOT NULL,
    entry_id uuid NOT NULL,
    version integer NOT NULL,
    CONSTRAINT pk_knowledge_recalls PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uq_knowledge_recalls_org_id_session_id_entry_id ON core.knowledge_recalls (org_id, session_id, entry_id);

ALTER TABLE core.knowledge_recalls ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.knowledge_recalls FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_fence ON core.knowledge_recalls
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
