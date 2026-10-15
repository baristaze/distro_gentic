-- Knowledge is agent knowledge: the kinds of the events it announced
-- move in place.

-- The kinds of the events they announce move in place.
ALTER TABLE activity.change_events NO FORCE ROW LEVEL SECURITY;
UPDATE activity.change_events SET kind = CASE kind
        WHEN 'knowledge.entry.created' THEN 'agent_knowledge.entry.created'
        WHEN 'knowledge.entry.updated' THEN 'agent_knowledge.entry.updated'
    END
    WHERE kind IN ('knowledge.entry.created', 'knowledge.entry.updated');
UPDATE activity.change_events
    SET payload = jsonb_set(payload, '{kind}', to_jsonb(CASE payload ->> 'kind'
        WHEN 'knowledge.entry.created' THEN 'agent_knowledge.entry.created'
        WHEN 'knowledge.entry.updated' THEN 'agent_knowledge.entry.updated'
    END))
    WHERE kind = 'outbox.row.failed' AND payload ->> 'kind' IN ('knowledge.entry.created', 'knowledge.entry.updated');
ALTER TABLE activity.change_events FORCE ROW LEVEL SECURITY;
