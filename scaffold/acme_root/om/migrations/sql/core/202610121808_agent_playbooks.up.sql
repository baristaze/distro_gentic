-- A playbook is an agent playbook: its three tables, their columns, and
-- their indexes take the name, and every row stays.

ALTER TABLE core.playbooks RENAME TO agent_playbooks;
ALTER TABLE core.agent_playbooks RENAME CONSTRAINT pk_playbooks TO pk_agent_playbooks;
ALTER INDEX core.uq_playbooks_org_id_name_version RENAME TO uq_agent_playbooks_org_id_name_version;

ALTER TABLE core.playbook_invocations RENAME TO agent_playbook_invocations;
ALTER TABLE core.agent_playbook_invocations RENAME COLUMN playbook_id TO agent_playbook_id;
ALTER TABLE core.agent_playbook_invocations RENAME CONSTRAINT pk_playbook_invocations TO pk_agent_playbook_invocations;
ALTER INDEX core.uq_playbook_invocations_org_id_session_id_playbook_id RENAME TO uq_agent_playbook_invocations_org_id_session_id_agent_playbook;

ALTER TABLE core.playbook_pins RENAME TO agent_playbook_pins;
ALTER TABLE core.agent_playbook_pins RENAME COLUMN playbook_id TO agent_playbook_id;
ALTER TABLE core.agent_playbook_pins RENAME CONSTRAINT pk_playbook_pins TO pk_agent_playbook_pins;
ALTER INDEX core.uq_playbook_pins_org_id_kind_project_id RENAME TO uq_agent_playbook_pins_org_id_kind_project_id;

-- An agent automation's action names the agent playbook it invokes.
ALTER TABLE core.agent_automations NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_automations
    SET action = (action - 'playbook') || jsonb_build_object('agent_playbook', action -> 'playbook')
    WHERE action ? 'playbook';
ALTER TABLE core.agent_automations FORCE ROW LEVEL SECURITY;

-- The kinds of the events they announce move in place.
ALTER TABLE core.outbox_rows NO FORCE ROW LEVEL SECURITY;
UPDATE core.outbox_rows SET kind = CASE kind
        WHEN 'playbooks.playbook.created' THEN 'agent_playbooks.agent_playbook.created'
        WHEN 'playbooks.pin.updated' THEN 'agent_playbooks.pin.updated'
        WHEN 'playbooks.pin.deleted' THEN 'agent_playbooks.pin.deleted'
    END
    WHERE kind IN ('playbooks.playbook.created', 'playbooks.pin.updated', 'playbooks.pin.deleted');
ALTER TABLE core.outbox_rows FORCE ROW LEVEL SECURITY;
