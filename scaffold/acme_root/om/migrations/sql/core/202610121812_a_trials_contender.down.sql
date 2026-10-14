-- The release before reads the names it wrote. Every row stays.

UPDATE core.benchmarks SET trials = (
    SELECT jsonb_agg(
        CASE WHEN t ? 'contender' THEN (t - 'contender') || jsonb_build_object('arm', t -> 'contender') ELSE t END
        ORDER BY o
    )
    FROM jsonb_array_elements(trials) WITH ORDINALITY AS x (t, o)
)
    WHERE jsonb_path_exists(trials, '$[*] ? (exists (@.contender))');
