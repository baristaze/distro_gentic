-- Takes the relay back out: each fence, then each table.

DROP POLICY tenant_fence ON core.workspace_bindings;
DROP POLICY tenant_fence ON core.exec_controls;
DROP POLICY tenant_fence ON core.exec_parts;
DROP POLICY tenant_fence ON core.exec_items;
DROP TABLE core.workspace_bindings;
DROP TABLE core.exec_controls;
DROP TABLE core.exec_parts;
DROP TABLE core.exec_items;
