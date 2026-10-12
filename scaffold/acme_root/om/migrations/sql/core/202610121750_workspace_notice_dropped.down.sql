-- Puts the one notice back beside the list, with the list's default, as
-- the release before held them: the last notice written fills the column,
-- every tenant's, under the fence lifted for this transaction alone, and
-- the rows touched are held to the rows counted.

ALTER TABLE core.session_workspaces ADD COLUMN notice text;
ALTER TABLE core.session_workspaces ALTER COLUMN notices SET DEFAULT '[]'::jsonb;

ALTER TABLE core.session_workspaces NO FORCE ROW LEVEL SECURITY;
DO $$
DECLARE
    expected bigint;
    touched bigint;
BEGIN
    SELECT count(*) INTO expected FROM core.session_workspaces WHERE notices <> '[]'::jsonb;
    UPDATE core.session_workspaces SET notice = notices ->> -1 WHERE notices <> '[]'::jsonb;
    GET DIAGNOSTICS touched = ROW_COUNT;
    IF touched <> expected THEN
        RAISE EXCEPTION 'the notice of core.session_workspaces: % rows of %', touched, expected;
    END IF;
END
$$;
ALTER TABLE core.session_workspaces FORCE ROW LEVEL SECURITY;
