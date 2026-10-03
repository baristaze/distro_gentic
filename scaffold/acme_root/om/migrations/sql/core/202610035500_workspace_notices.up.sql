-- What a session's workspace tells its next loop, one entry an instance let
-- go since a loop was last told, in place of the one notice a later release
-- wrote over. The previous release inserts without naming the list for the
-- minutes of the roll, so it keeps its empty default until the one notice's
-- column leaves the table, a release after it leaves the mapping (ADR 0038).

ALTER TABLE core.session_workspaces ADD COLUMN notices jsonb NOT NULL DEFAULT '[]'::jsonb;

-- The one notice moves in, every tenant's. The migration login owns the
-- table and FORCE binds the owner, so the fence is lifted for this
-- transaction alone, and the rows touched are held to the rows counted.
ALTER TABLE core.session_workspaces NO FORCE ROW LEVEL SECURITY;
DO $$
DECLARE
    expected bigint;
    touched bigint;
BEGIN
    SELECT count(*) INTO expected FROM core.session_workspaces WHERE notice IS NOT NULL;
    UPDATE core.session_workspaces SET notices = jsonb_build_array(notice)
        WHERE notice IS NOT NULL;
    GET DIAGNOSTICS touched = ROW_COUNT;
    IF touched <> expected THEN
        RAISE EXCEPTION 'the notices of core.session_workspaces: % rows of %', touched, expected;
    END IF;
END
$$;
ALTER TABLE core.session_workspaces FORCE ROW LEVEL SECURITY;
