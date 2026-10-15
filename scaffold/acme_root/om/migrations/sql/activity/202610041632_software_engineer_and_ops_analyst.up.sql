-- The engineer kind is the software engineer and the operator kind the
-- ops analyst: usage records and pin events carry the new kind ids.

ALTER TABLE activity.usage_records NO FORCE ROW LEVEL SECURITY;
UPDATE activity.usage_records SET agent_kind = CASE agent_kind WHEN 'engineer' THEN 'software_engineer' WHEN 'operator' THEN 'ops_analyst' END WHERE agent_kind IN ('engineer', 'operator');
ALTER TABLE activity.usage_records FORCE ROW LEVEL SECURITY;
ALTER TABLE activity.change_events NO FORCE ROW LEVEL SECURITY;
UPDATE activity.change_events SET payload = jsonb_set(payload, '{kind}', to_jsonb(CASE payload ->> 'kind' WHEN 'engineer' THEN 'software_engineer' WHEN 'operator' THEN 'ops_analyst' END)) WHERE kind IN ('agent_playbooks.pin.updated', 'agent_playbooks.pin.deleted') AND payload ->> 'kind' IN ('engineer', 'operator');
ALTER TABLE activity.change_events FORCE ROW LEVEL SECURITY;
