-- Takes the rows of intake, automations, playbooks, and knowledge back
-- out: each fence, then its table.

DROP POLICY tenant_fence ON core.knowledge_entries;
DROP TABLE core.knowledge_entries;
DROP POLICY tenant_fence ON core.playbook_invocations;
DROP TABLE core.playbook_invocations;
DROP POLICY tenant_fence ON core.playbooks;
DROP TABLE core.playbooks;
DROP POLICY tenant_fence ON core.automation_runs;
DROP TABLE core.automation_runs;
DROP POLICY tenant_fence ON core.automations;
DROP TABLE core.automations;
DROP POLICY tenant_fence ON core.work_bindings;
DROP TABLE core.work_bindings;
DROP POLICY tenant_fence ON core.account_links;
DROP TABLE core.account_links;
