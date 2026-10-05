-- Takes the validation session's key back out.

ALTER TABLE core.validation_sessions
    DROP COLUMN key_id;
