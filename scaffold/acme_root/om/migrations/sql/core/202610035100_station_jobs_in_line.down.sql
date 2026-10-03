-- Drops the jobs line entries carry, and the station job a run names.

ALTER TABLE core.automation_runs DROP COLUMN job_id;
ALTER TABLE core.station_line_entries DROP COLUMN commands;
