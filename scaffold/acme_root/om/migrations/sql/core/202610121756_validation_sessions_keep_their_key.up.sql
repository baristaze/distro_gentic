-- A validation session keeps the API key it was started on, and its run
-- acts on its starter's authority no higher than that key. A session
-- stored before this change, or one the previous release writes during a
-- roll, names no key and runs at its starter's own role, as a session
-- started in person does.

ALTER TABLE core.validation_sessions
    ADD COLUMN key_id uuid;
