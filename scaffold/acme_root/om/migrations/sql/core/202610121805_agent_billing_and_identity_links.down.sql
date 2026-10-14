-- The release before reads the names it wrote. Every row stays.

ALTER TABLE core.outbox_rows NO FORCE ROW LEVEL SECURITY;
UPDATE core.outbox_rows SET kind = CASE kind
        WHEN 'agent_billing.spend_account.created' THEN 'billing.account.created'
        WHEN 'agent_billing.spend_account.updated' THEN 'billing.account.updated'
        WHEN 'intake.identity_link.deleted' THEN 'intake.account_link.deleted'
    END
    WHERE kind IN ('agent_billing.spend_account.created', 'agent_billing.spend_account.updated', 'intake.identity_link.deleted');
ALTER TABLE core.outbox_rows FORCE ROW LEVEL SECURITY;

ALTER TABLE core.identity_links RENAME CONSTRAINT pk_identity_links TO pk_account_links;
ALTER INDEX core.ix_identity_links_org_id_user_id RENAME TO ix_account_links_org_id_user_id;
ALTER INDEX core.uq_identity_links_org_id_integration_external_id RENAME TO uq_account_links_org_id_integration_external_id;
ALTER TABLE core.identity_links RENAME TO account_links;

ALTER TABLE core.spend_accounts RENAME CONSTRAINT pk_spend_accounts TO pk_billing_accounts;
ALTER INDEX core.ix_spend_accounts_org_id RENAME TO ix_billing_accounts_org_id;
ALTER TABLE core.spend_accounts RENAME COLUMN unit_plan_id TO plan_id;
ALTER TABLE core.spend_accounts RENAME COLUMN unit_plan_version TO plan_version;
ALTER TABLE core.spend_accounts RENAME TO billing_accounts;
