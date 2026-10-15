-- The release before reads the names it wrote. Every row stays.

ALTER TABLE activity.change_events NO FORCE ROW LEVEL SECURITY;
UPDATE activity.change_events SET kind = CASE kind
        WHEN 'agent_knowledge.entry.created' THEN 'knowledge.entry.created'
        WHEN 'agent_knowledge.entry.updated' THEN 'knowledge.entry.updated'
    END
    WHERE kind IN ('agent_knowledge.entry.created', 'agent_knowledge.entry.updated');
UPDATE activity.change_events
    SET payload = jsonb_set(payload, '{kind}', to_jsonb(CASE payload ->> 'kind'
        WHEN 'agent_knowledge.entry.created' THEN 'knowledge.entry.created'
        WHEN 'agent_knowledge.entry.updated' THEN 'knowledge.entry.updated'
    END))
    WHERE kind = 'outbox.row.failed' AND payload ->> 'kind' IN ('agent_knowledge.entry.created', 'agent_knowledge.entry.updated');
ALTER TABLE activity.change_events FORCE ROW LEVEL SECURITY;
