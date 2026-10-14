-- A project's environment is its workspace base: the column takes the
-- name, and every value stays.
ALTER TABLE core.projects RENAME COLUMN environment TO workspace_base;

-- A declared check names the executor that runs it. Each check of every
-- tenant's policy moves the key in place, in its order; a check that
-- names none still names none. The migration login owns the table and
-- FORCE binds the owner, so the fence is lifted for this transaction alone.
ALTER TABLE core.validation_policies NO FORCE ROW LEVEL SECURITY;
UPDATE core.validation_policies SET checks = (
    SELECT jsonb_agg(
        CASE WHEN c ? 'environment'
            THEN (c - 'environment') || jsonb_build_object('executor', c -> 'environment')
            ELSE c
        END
        ORDER BY o
    )
    FROM jsonb_array_elements(checks) WITH ORDINALITY AS t (c, o)
)
    WHERE jsonb_path_exists(checks, '$[*] ? (exists (@.environment))');
ALTER TABLE core.validation_policies FORCE ROW LEVEL SECURITY;

-- A benchmark keeps the hidden suite's runs whole, each a record that now
-- names its run image. The key moves in place in every trial; a record's
-- image is the one object that opens with it.
UPDATE core.benchmarks
    SET trials = replace(trials::text, '"environment": {"image":', '"run_image": {"image":')::jsonb
    WHERE trials::text LIKE '%"environment": {"image":%';
