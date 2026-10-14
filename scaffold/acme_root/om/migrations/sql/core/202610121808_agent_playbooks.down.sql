-- The release before reads the names it wrote. Every row stays.

ALTER TABLE core.outbox_rows NO FORCE ROW LEVEL SECURITY;
UPDATE core.outbox_rows SET kind = CASE kind
        WHEN 'agent_playbooks.agent_playbook.created' THEN 'playbooks.playbook.created'
        WHEN 'agent_playbooks.pin.updated' THEN 'playbooks.pin.updated'
        WHEN 'agent_playbooks.pin.deleted' THEN 'playbooks.pin.deleted'
    END
    WHERE kind IN ('agent_playbooks.agent_playbook.created', 'agent_playbooks.pin.updated', 'agent_playbooks.pin.deleted');
ALTER TABLE core.outbox_rows FORCE ROW LEVEL SECURITY;

ALTER TABLE core.agent_automations NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_automations
    SET action = (action - 'agent_playbook') || jsonb_build_object('playbook', action -> 'agent_playbook')
    WHERE action ? 'agent_playbook';
ALTER TABLE core.agent_automations FORCE ROW LEVEL SECURITY;

ALTER TABLE core.agent_playbook_pins RENAME CONSTRAINT pk_agent_playbook_pins TO pk_playbook_pins;
ALTER INDEX core.uq_agent_playbook_pins_org_id_kind_project_id RENAME TO uq_playbook_pins_org_id_kind_project_id;
ALTER TABLE core.agent_playbook_pins RENAME COLUMN agent_playbook_id TO playbook_id;
ALTER TABLE core.agent_playbook_pins RENAME TO playbook_pins;

ALTER TABLE core.agent_playbook_invocations RENAME CONSTRAINT pk_agent_playbook_invocations TO pk_playbook_invocations;
ALTER INDEX core.uq_agent_playbook_invocations_org_id_session_id_agent_playbook RENAME TO uq_playbook_invocations_org_id_session_id_playbook_id;
ALTER TABLE core.agent_playbook_invocations RENAME COLUMN agent_playbook_id TO playbook_id;
ALTER TABLE core.agent_playbook_invocations RENAME TO playbook_invocations;

ALTER TABLE core.agent_playbooks RENAME CONSTRAINT pk_agent_playbooks TO pk_playbooks;
ALTER INDEX core.uq_agent_playbooks_org_id_name_version RENAME TO uq_playbooks_org_id_name_version;
ALTER TABLE core.agent_playbooks RENAME TO playbooks;
