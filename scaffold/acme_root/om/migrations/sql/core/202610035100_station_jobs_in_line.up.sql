-- A line entry may carry its job: a session's ask carries none, so every
-- entry written before takes the empty list.

ALTER TABLE core.station_line_entries ADD COLUMN commands jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE core.station_line_entries ALTER COLUMN commands DROP DEFAULT;

-- The station job an automation's run runs, named once it joined the line.

ALTER TABLE core.automation_runs ADD COLUMN job_id uuid;
