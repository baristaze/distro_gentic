-- Takes the automation principal, the channel index, and the notifications
-- back out: each fence, then its table, then the column.

DROP POLICY tenant_fence ON core.notifications;
DROP TABLE core.notifications;
DROP INDEX core.ix_account_links_org_id_user_id;
DROP POLICY tenant_fence ON core.automation_principals;
DROP TABLE core.automation_principals;
ALTER TABLE core.automations DROP COLUMN runs_as;
