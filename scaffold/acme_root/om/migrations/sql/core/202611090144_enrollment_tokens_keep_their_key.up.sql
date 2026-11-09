-- An enrollment token keeps the API key it was issued on, and it enrolls
-- on its issuer's authority no higher than that key, only while the key
-- holds. A token stored before this change, or one the previous release
-- issues during a roll, names no key and enrolls on its issuer's own
-- role, as a token issued in person does.

ALTER TABLE core.host_enrollment_tokens
    ADD COLUMN key_id uuid;
