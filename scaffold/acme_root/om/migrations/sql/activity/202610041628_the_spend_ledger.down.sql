-- The release before reads the names it wrote. Every row stays.

ALTER TABLE activity.events NO FORCE ROW LEVEL SECURITY;
UPDATE activity.events SET kind = CASE kind
        WHEN 'agent_billing.spend_account.created' THEN 'billing.account.created'
        WHEN 'agent_billing.spend_account.updated' THEN 'billing.account.updated'
        WHEN 'intake.identity_link.deleted' THEN 'intake.account_link.deleted'
    END
    WHERE kind IN ('agent_billing.spend_account.created', 'agent_billing.spend_account.updated', 'intake.identity_link.deleted');
UPDATE activity.events
    SET payload = jsonb_set(payload, '{kind}', to_jsonb(CASE payload ->> 'kind'
        WHEN 'agent_billing.spend_account.created' THEN 'billing.account.created'
        WHEN 'agent_billing.spend_account.updated' THEN 'billing.account.updated'
        WHEN 'intake.identity_link.deleted' THEN 'intake.account_link.deleted'
    END))
    WHERE kind = 'outbox.row.failed' AND payload ->> 'kind' IN ('agent_billing.spend_account.created', 'agent_billing.spend_account.updated', 'intake.identity_link.deleted');
ALTER TABLE activity.events FORCE ROW LEVEL SECURITY;

ALTER TABLE activity.spend_ledger_entries NO FORCE ROW LEVEL SECURITY;
UPDATE activity.spend_ledger_entries
    SET body = jsonb_set(body #- '{funding,unit_plan}', '{funding,plan}', body #> '{funding,unit_plan}')
    WHERE body #> '{funding,unit_plan}' IS NOT NULL;
ALTER TABLE activity.spend_ledger_entries FORCE ROW LEVEL SECURITY;

ALTER TABLE activity.spend_ledger_counts RENAME CONSTRAINT pk_spend_ledger_counts TO pk_ledger_counts;
ALTER TABLE activity.spend_ledger_counts RENAME TO ledger_counts;

ALTER TABLE activity.spend_ledger_entries RENAME CONSTRAINT pk_spend_ledger_entries TO pk_ledger_entries;
ALTER INDEX activity.ix_spend_ledger_entries_kind_created_at RENAME TO ix_ledger_entries_kind_created_at;
ALTER INDEX activity.ix_spend_ledger_entries_kind_deadline RENAME TO ix_ledger_entries_kind_deadline;
ALTER INDEX activity.ix_spend_ledger_entries_org_id_hold_id RENAME TO ix_ledger_entries_org_id_hold_id;
ALTER INDEX activity.ix_spend_ledger_entries_org_id_kind_created_at RENAME TO ix_ledger_entries_org_id_kind_created_at;
ALTER INDEX activity.ix_spend_ledger_entries_org_id_session_id_created_at RENAME TO ix_ledger_entries_org_id_session_id_created_at;
ALTER INDEX activity.uq_spend_ledger_entries_org_id_kind_hold_id RENAME TO uq_ledger_entries_org_id_kind_hold_id;
ALTER INDEX activity.uq_spend_ledger_entries_org_id_kind_reference RENAME TO uq_ledger_entries_org_id_kind_reference;
ALTER TABLE activity.spend_ledger_entries RENAME TO ledger_entries;
