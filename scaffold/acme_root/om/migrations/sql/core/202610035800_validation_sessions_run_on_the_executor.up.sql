-- A validation session runs a delivery's check on a fresh executor: it
-- names its project, the commit it runs at, and the commit its checks come
-- from. The previous release inserts without naming them for the minutes
-- of the roll, so they are nullable until the station's columns leave the
-- table, a release after they leave the mapping (ADR 0038). This release
-- inserts without naming those, so they lose their NOT NULL now. A row the
-- previous release wrote keeps its lab, and is kept.

ALTER TABLE core.validation_sessions
    ADD COLUMN project_id uuid,
    ADD COLUMN head text,
    ADD COLUMN base text,
    ALTER COLUMN lab_id DROP NOT NULL,
    ALTER COLUMN check_version DROP NOT NULL,
    ALTER COLUMN parameters DROP NOT NULL;
