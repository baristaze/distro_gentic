-- Knowledge is agent knowledge: its two tables and their indexes take
-- the name, and every entry and recall stays.

ALTER TABLE core.knowledge_entries RENAME TO agent_knowledge_entries;
ALTER TABLE core.agent_knowledge_entries RENAME CONSTRAINT pk_knowledge_entries TO pk_agent_knowledge_entries;
ALTER INDEX core.ix_knowledge_entries_org_id_slug RENAME TO ix_agent_knowledge_entries_org_id_slug;
ALTER INDEX core.ix_knowledge_entries_org_id_status_id RENAME TO ix_agent_knowledge_entries_org_id_status_id;

ALTER TABLE core.knowledge_recalls RENAME TO agent_knowledge_recalls;
ALTER TABLE core.agent_knowledge_recalls RENAME CONSTRAINT pk_knowledge_recalls TO pk_agent_knowledge_recalls;
ALTER INDEX core.uq_knowledge_recalls_org_id_session_id_entry_id RENAME TO uq_agent_knowledge_recalls_org_id_session_id_entry_id;

-- The tools' new names move in place where a session pinned them and
-- where a policy's rule or a gate names one.
ALTER TABLE core.agent_sessions NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_sessions SET tools = (
    SELECT jsonb_agg(to_jsonb(CASE t WHEN 'search_knowledge' THEN 'search_agent_knowledge' WHEN 'read_knowledge' THEN 'read_agent_knowledge' WHEN 'suggest_knowledge' THEN 'suggest_agent_knowledge' ELSE t END) ORDER BY o)
    FROM jsonb_array_elements_text(tools) WITH ORDINALITY AS x (t, o)
)
    WHERE tools ?| ARRAY['search_knowledge', 'read_knowledge', 'suggest_knowledge'];
ALTER TABLE core.agent_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE core.tool_policies NO FORCE ROW LEVEL SECURITY;
UPDATE core.tool_policies SET rules = (
    SELECT jsonb_agg(
        CASE WHEN r ->> 'tool' IN ('search_knowledge', 'read_knowledge', 'suggest_knowledge')
            THEN jsonb_set(r, '{tool}', to_jsonb(CASE r ->> 'tool' WHEN 'search_knowledge' THEN 'search_agent_knowledge' WHEN 'read_knowledge' THEN 'read_agent_knowledge' WHEN 'suggest_knowledge' THEN 'suggest_agent_knowledge' ELSE r ->> 'tool' END))
            ELSE r
        END
        ORDER BY o
    )
    FROM jsonb_array_elements(rules) WITH ORDINALITY AS x (r, o)
)
    WHERE jsonb_path_exists(rules, '$[*] ? (@.tool == "search_knowledge" || @.tool == "read_knowledge" || @.tool == "suggest_knowledge")');
ALTER TABLE core.tool_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE core.playbooks NO FORCE ROW LEVEL SECURITY;
UPDATE core.playbooks SET gates = (
    SELECT jsonb_agg(
        CASE WHEN r ->> 'tool' IN ('search_knowledge', 'read_knowledge', 'suggest_knowledge')
            THEN jsonb_set(r, '{tool}', to_jsonb(CASE r ->> 'tool' WHEN 'search_knowledge' THEN 'search_agent_knowledge' WHEN 'read_knowledge' THEN 'read_agent_knowledge' WHEN 'suggest_knowledge' THEN 'suggest_agent_knowledge' ELSE r ->> 'tool' END))
            ELSE r
        END
        ORDER BY o
    )
    FROM jsonb_array_elements(gates) WITH ORDINALITY AS x (r, o)
)
    WHERE jsonb_path_exists(gates, '$[*] ? (@.tool == "search_knowledge" || @.tool == "read_knowledge" || @.tool == "suggest_knowledge")');
ALTER TABLE core.playbooks FORCE ROW LEVEL SECURITY;

-- The kinds of the events they announce move in place.
ALTER TABLE core.outbox_rows NO FORCE ROW LEVEL SECURITY;
UPDATE core.outbox_rows SET kind = CASE kind
        WHEN 'knowledge.entry.created' THEN 'agent_knowledge.entry.created'
        WHEN 'knowledge.entry.updated' THEN 'agent_knowledge.entry.updated'
    END
    WHERE kind IN ('knowledge.entry.created', 'knowledge.entry.updated');
ALTER TABLE core.outbox_rows FORCE ROW LEVEL SECURITY;
