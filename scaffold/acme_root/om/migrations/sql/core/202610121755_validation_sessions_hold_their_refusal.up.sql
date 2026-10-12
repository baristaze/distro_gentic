-- A validation session whose check cannot run here, for good, is refused
-- and holds why. The previous release inserts without naming the column
-- for the minutes of the roll, so it takes a null, as every session that
-- is not refused holds.

ALTER TABLE core.validation_sessions ADD COLUMN refusal text;
