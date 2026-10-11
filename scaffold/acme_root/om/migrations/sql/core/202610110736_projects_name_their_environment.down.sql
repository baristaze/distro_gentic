-- Takes each project's environment back out: every session's workspace
-- starts from its kind's own again. A session pinned to one keeps it.

ALTER TABLE core.projects DROP COLUMN environment;
