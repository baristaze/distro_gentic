-- The one notice `notices` replaced leaves the table, a release after it
-- left the mapping (ADR 0038). The previous release names the list in
-- every insert, so the list's default goes with it. Every notice a loop
-- has not been told is in the list already; the column holds only the
-- one a release before the list wrote, which nothing reads.

ALTER TABLE core.session_workspaces DROP COLUMN notice;
ALTER TABLE core.session_workspaces ALTER COLUMN notices DROP DEFAULT;
