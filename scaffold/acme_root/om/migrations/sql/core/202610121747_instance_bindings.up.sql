-- A run that validates a pinned session's delivery makes an instance of its
-- own on a host of the session's pool, bound as a session's workspace is.
-- Its binding names the session it was made for, whose placement routes it
-- and whose project its host's owner holds its work to. A session's own
-- binding names none, so the column is nullable, and the previous release
-- writes rows without it for the minutes of the roll.

ALTER TABLE core.workspace_bindings ADD COLUMN instance_of uuid;
