-- The release before reads the names it wrote. Every row stays.

ALTER TABLE core.agent_sessions NO FORCE ROW LEVEL SECURITY;
UPDATE core.agent_sessions SET tools = (
    SELECT jsonb_agg(to_jsonb(CASE t WHEN 'search_agent_knowledge' THEN 'search_knowledge' WHEN 'read_agent_knowledge' THEN 'read_knowledge' WHEN 'suggest_agent_knowledge' THEN 'suggest_knowledge' ELSE t END) ORDER BY o)
    FROM jsonb_array_elements_text(tools) WITH ORDINALITY AS x (t, o)
)
    WHERE tools ?| ARRAY['search_agent_knowledge', 'read_agent_knowledge', 'suggest_agent_knowledge'];
ALTER TABLE core.agent_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE core.tool_policies NO FORCE ROW LEVEL SECURITY;
UPDATE core.tool_policies SET rules = (
    SELECT jsonb_agg(
        CASE WHEN r ->> 'tool' IN ('search_agent_knowledge', 'read_agent_knowledge', 'suggest_agent_knowledge')
            THEN jsonb_set(r, '{tool}', to_jsonb(CASE r ->> 'tool' WHEN 'search_agent_knowledge' THEN 'search_knowledge' WHEN 'read_agent_knowledge' THEN 'read_knowledge' WHEN 'suggest_agent_knowledge' THEN 'suggest_knowledge' ELSE r ->> 'tool' END))
            ELSE r
        END
        ORDER BY o
    )
    FROM jsonb_array_elements(rules) WITH ORDINALITY AS x (r, o)
)
    WHERE jsonb_path_exists(rules, '$[*] ? (@.tool == "search_agent_knowledge" || @.tool == "read_agent_knowledge" || @.tool == "suggest_agent_knowledge")');
ALTER TABLE core.tool_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE core.playbooks NO FORCE ROW LEVEL SECURITY;
UPDATE core.playbooks SET gates = (
    SELECT jsonb_agg(
        CASE WHEN r ->> 'tool' IN ('search_agent_knowledge', 'read_agent_knowledge', 'suggest_agent_knowledge')
            THEN jsonb_set(r, '{tool}', to_jsonb(CASE r ->> 'tool' WHEN 'search_agent_knowledge' THEN 'search_knowledge' WHEN 'read_agent_knowledge' THEN 'read_knowledge' WHEN 'suggest_agent_knowledge' THEN 'suggest_knowledge' ELSE r ->> 'tool' END))
            ELSE r
        END
        ORDER BY o
    )
    FROM jsonb_array_elements(gates) WITH ORDINALITY AS x (r, o)
)
    WHERE jsonb_path_exists(gates, '$[*] ? (@.tool == "search_agent_knowledge" || @.tool == "read_agent_knowledge" || @.tool == "suggest_agent_knowledge")');
ALTER TABLE core.playbooks FORCE ROW LEVEL SECURITY;

ALTER TABLE core.outbox_rows NO FORCE ROW LEVEL SECURITY;
UPDATE core.outbox_rows SET kind = CASE kind
        WHEN 'agent_knowledge.entry.created' THEN 'knowledge.entry.created'
        WHEN 'agent_knowledge.entry.updated' THEN 'knowledge.entry.updated'
    END
    WHERE kind IN ('agent_knowledge.entry.created', 'agent_knowledge.entry.updated');
ALTER TABLE core.outbox_rows FORCE ROW LEVEL SECURITY;

ALTER TABLE core.agent_knowledge_recalls RENAME CONSTRAINT pk_agent_knowledge_recalls TO pk_knowledge_recalls;
ALTER INDEX core.uq_agent_knowledge_recalls_org_id_session_id_entry_id RENAME TO uq_knowledge_recalls_org_id_session_id_entry_id;
ALTER TABLE core.agent_knowledge_recalls RENAME TO knowledge_recalls;

ALTER TABLE core.agent_knowledge_entries RENAME CONSTRAINT pk_agent_knowledge_entries TO pk_knowledge_entries;
ALTER INDEX core.ix_agent_knowledge_entries_org_id_slug RENAME TO ix_knowledge_entries_org_id_slug;
ALTER INDEX core.ix_agent_knowledge_entries_org_id_status_id RENAME TO ix_knowledge_entries_org_id_status_id;
ALTER TABLE core.agent_knowledge_entries RENAME TO knowledge_entries;
