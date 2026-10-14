-- The release before reads a project's environment and a check's
-- environment: the names go back, and every value stays.
ALTER TABLE core.validation_policies NO FORCE ROW LEVEL SECURITY;
UPDATE core.validation_policies SET checks = (
    SELECT jsonb_agg(
        CASE WHEN c ? 'executor'
            THEN (c - 'executor') || jsonb_build_object('environment', c -> 'executor')
            ELSE c
        END
        ORDER BY o
    )
    FROM jsonb_array_elements(checks) WITH ORDINALITY AS t (c, o)
)
    WHERE jsonb_path_exists(checks, '$[*] ? (exists (@.executor))');
ALTER TABLE core.validation_policies FORCE ROW LEVEL SECURITY;

UPDATE core.benchmarks
    SET trials = replace(trials::text, '"run_image": {"image":', '"environment": {"image":')::jsonb
    WHERE trials::text LIKE '%"run_image": {"image":%';

ALTER TABLE core.projects RENAME COLUMN workspace_base TO environment;
