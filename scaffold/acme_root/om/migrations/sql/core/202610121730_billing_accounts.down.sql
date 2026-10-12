-- Takes the billing accounts back out: the fence, then the table.

DROP POLICY tenant_fence ON core.billing_accounts;
DROP TABLE core.billing_accounts;
