-- A benchmark's trial names the contender it ran for, the candidate or
-- the baseline: the key moves in place in every trial.

UPDATE core.benchmarks SET trials = (
    SELECT jsonb_agg(
        CASE WHEN t ? 'arm' THEN (t - 'arm') || jsonb_build_object('contender', t -> 'arm') ELSE t END
        ORDER BY o
    )
    FROM jsonb_array_elements(trials) WITH ORDINALITY AS x (t, o)
)
    WHERE jsonb_path_exists(trials, '$[*] ? (exists (@.arm))');
