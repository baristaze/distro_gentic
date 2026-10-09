-- A run of a product's own automation action names the work it started
-- and, once the product's check says that work ended, how it ended. A run
-- of the platform's actions names neither, and the previous release writes
-- rows without them for the minutes of the roll, so both are nullable.

ALTER TABLE core.automation_runs ADD COLUMN work_id uuid;
ALTER TABLE core.automation_runs ADD COLUMN outcome text;
