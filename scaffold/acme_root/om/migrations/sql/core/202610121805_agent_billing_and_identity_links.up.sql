-- Agent billing's account is a spend account on a unit plan, and
-- intake's link of an outside identity to a user is an identity link.
-- The tables, their columns, and their indexes take the names; every
-- row stays.

ALTER TABLE core.billing_accounts RENAME TO spend_accounts;
ALTER TABLE core.spend_accounts RENAME COLUMN plan_id TO unit_plan_id;
ALTER TABLE core.spend_accounts RENAME COLUMN plan_version TO unit_plan_version;
ALTER TABLE core.spend_accounts RENAME CONSTRAINT pk_billing_accounts TO pk_spend_accounts;
ALTER INDEX core.ix_billing_accounts_org_id RENAME TO ix_spend_accounts_org_id;

ALTER TABLE core.account_links RENAME TO identity_links;
ALTER TABLE core.identity_links RENAME CONSTRAINT pk_account_links TO pk_identity_links;
ALTER INDEX core.ix_account_links_org_id_user_id RENAME TO ix_identity_links_org_id_user_id;
ALTER INDEX core.uq_account_links_org_id_integration_external_id RENAME TO uq_identity_links_org_id_integration_external_id;

-- The kinds of the events they announce move in place.
ALTER TABLE core.outbox_rows NO FORCE ROW LEVEL SECURITY;
UPDATE core.outbox_rows SET kind = CASE kind
        WHEN 'billing.account.created' THEN 'agent_billing.spend_account.created'
        WHEN 'billing.account.updated' THEN 'agent_billing.spend_account.updated'
        WHEN 'intake.account_link.deleted' THEN 'intake.identity_link.deleted'
    END
    WHERE kind IN ('billing.account.created', 'billing.account.updated', 'intake.account_link.deleted');
ALTER TABLE core.outbox_rows FORCE ROW LEVEL SECURITY;
