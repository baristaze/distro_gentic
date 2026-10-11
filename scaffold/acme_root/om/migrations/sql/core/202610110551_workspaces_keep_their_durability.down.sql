-- Takes the records of where each snapshot lives back out, with each
-- project's say and each pin's durability and base: every workspace is a
-- cache on its provider's own image again.

DROP TABLE core.workspace_snapshots;
ALTER TABLE core.projects DROP COLUMN workspace_snapshots;
ALTER TABLE core.session_workspaces DROP COLUMN base;
ALTER TABLE core.session_workspaces DROP COLUMN durability;
