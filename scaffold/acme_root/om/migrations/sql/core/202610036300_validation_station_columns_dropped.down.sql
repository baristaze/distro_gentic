-- Puts the station's columns back as the release before held them:
-- nullable, and null in every row, since no row this release kept names a
-- lab. The columns the model holds lose their NOT NULL. A row the up
-- migration deleted does not come back.

ALTER TABLE core.validation_sessions
    ADD COLUMN lab_id uuid,
    ADD COLUMN check_version text,
    ADD COLUMN parameters jsonb,
    ALTER COLUMN project_id DROP NOT NULL,
    ALTER COLUMN head DROP NOT NULL,
    ALTER COLUMN base DROP NOT NULL;
