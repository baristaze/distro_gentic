-- Agent billing's ledger is the spend ledger: its two tables and their
-- indexes take the name, and every entry and count stays.

ALTER TABLE activity.ledger_entries RENAME TO spend_ledger_entries;
ALTER TABLE activity.spend_ledger_entries RENAME CONSTRAINT pk_ledger_entries TO pk_spend_ledger_entries;
ALTER INDEX activity.ix_ledger_entries_kind_created_at RENAME TO ix_spend_ledger_entries_kind_created_at;
ALTER INDEX activity.ix_ledger_entries_kind_deadline RENAME TO ix_spend_ledger_entries_kind_deadline;
ALTER INDEX activity.ix_ledger_entries_org_id_hold_id RENAME TO ix_spend_ledger_entries_org_id_hold_id;
ALTER INDEX activity.ix_ledger_entries_org_id_kind_created_at RENAME TO ix_spend_ledger_entries_org_id_kind_created_at;
ALTER INDEX activity.ix_ledger_entries_org_id_session_id_created_at RENAME TO ix_spend_ledger_entries_org_id_session_id_created_at;
ALTER INDEX activity.uq_ledger_entries_org_id_kind_hold_id RENAME TO uq_spend_ledger_entries_org_id_kind_hold_id;
ALTER INDEX activity.uq_ledger_entries_org_id_kind_reference RENAME TO uq_spend_ledger_entries_org_id_kind_reference;

ALTER TABLE activity.ledger_counts RENAME TO spend_ledger_counts;
ALTER TABLE activity.spend_ledger_counts RENAME CONSTRAINT pk_ledger_counts TO pk_spend_ledger_counts;

-- A hold names the unit plan it drew on: the key moves in place.
ALTER TABLE activity.spend_ledger_entries NO FORCE ROW LEVEL SECURITY;
UPDATE activity.spend_ledger_entries
    SET body = jsonb_set(body #- '{funding,plan}', '{funding,unit_plan}', body #> '{funding,plan}')
    WHERE body #> '{funding,plan}' IS NOT NULL;
ALTER TABLE activity.spend_ledger_entries FORCE ROW LEVEL SECURITY;

-- The kinds of the events they announce move in place.
ALTER TABLE activity.events NO FORCE ROW LEVEL SECURITY;
UPDATE activity.events SET kind = CASE kind
        WHEN 'billing.account.created' THEN 'agent_billing.spend_account.created'
        WHEN 'billing.account.updated' THEN 'agent_billing.spend_account.updated'
        WHEN 'intake.account_link.deleted' THEN 'intake.identity_link.deleted'
    END
    WHERE kind IN ('billing.account.created', 'billing.account.updated', 'intake.account_link.deleted');
UPDATE activity.events
    SET payload = jsonb_set(payload, '{kind}', to_jsonb(CASE payload ->> 'kind'
        WHEN 'billing.account.created' THEN 'agent_billing.spend_account.created'
        WHEN 'billing.account.updated' THEN 'agent_billing.spend_account.updated'
        WHEN 'intake.account_link.deleted' THEN 'intake.identity_link.deleted'
    END))
    WHERE kind = 'outbox.row.failed' AND payload ->> 'kind' IN ('billing.account.created', 'billing.account.updated', 'intake.account_link.deleted');
ALTER TABLE activity.events FORCE ROW LEVEL SECURITY;
