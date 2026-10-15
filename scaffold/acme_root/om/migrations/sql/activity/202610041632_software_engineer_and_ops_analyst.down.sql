-- The release before reads the names it wrote. Every row stays.

ALTER TABLE activity.usage_records NO FORCE ROW LEVEL SECURITY;
UPDATE activity.usage_records SET agent_kind = CASE agent_kind WHEN 'software_engineer' THEN 'engineer' WHEN 'ops_analyst' THEN 'operator' END WHERE agent_kind IN ('software_engineer', 'ops_analyst');
ALTER TABLE activity.usage_records FORCE ROW LEVEL SECURITY;
ALTER TABLE activity.change_events NO FORCE ROW LEVEL SECURITY;
UPDATE activity.change_events SET payload = jsonb_set(payload, '{kind}', to_jsonb(CASE payload ->> 'kind' WHEN 'software_engineer' THEN 'engineer' WHEN 'ops_analyst' THEN 'operator' END)) WHERE kind IN ('agent_playbooks.pin.updated', 'agent_playbooks.pin.deleted') AND payload ->> 'kind' IN ('software_engineer', 'ops_analyst');
ALTER TABLE activity.change_events FORCE ROW LEVEL SECURITY;
