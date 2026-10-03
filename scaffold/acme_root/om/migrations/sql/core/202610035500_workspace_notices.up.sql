-- What a session's workspace tells its next loop, one entry an instance let
-- go since a loop was last told, in place of the one notice a later release
-- wrote over. The previous release inserts without naming the list for the
-- minutes of the roll, so it keeps its empty default. The one notice moves
-- in after this, and its column stays until the release after (ADR 0038).

ALTER TABLE core.session_workspaces ADD COLUMN notices jsonb NOT NULL DEFAULT '[]'::jsonb;
