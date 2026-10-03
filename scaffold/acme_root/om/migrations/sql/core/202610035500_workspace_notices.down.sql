-- Takes the list back out. The previous release holds one notice: the last
-- one written moves back, every tenant's, under the same lifted fence and
-- count as the move in.

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

ALTER TABLE core.session_workspaces DROP COLUMN notices;
