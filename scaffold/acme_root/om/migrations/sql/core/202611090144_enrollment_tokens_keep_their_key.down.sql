-- Takes the enrollment token's key back out.

ALTER TABLE core.host_enrollment_tokens
    DROP COLUMN key_id;
