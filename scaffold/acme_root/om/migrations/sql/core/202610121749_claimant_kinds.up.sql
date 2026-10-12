-- The platform enrolls a claimant of any registered kind as it enrolls a
-- host: a token names the kind it enrolls, and the enrolled row names its
-- kind. Every row so far is a host's, and the previous release writes rows
-- without the column for the minutes of the roll, so the column defaults
-- to the host's kind. A claimant of a product's kind advertises nothing and
-- reads no `exec` work, so those two columns hold a host's alone.

ALTER TABLE core.host_enrollment_tokens ADD COLUMN kind text NOT NULL DEFAULT 'host';
ALTER TABLE core.hosts ADD COLUMN kind text NOT NULL DEFAULT 'host';
ALTER TABLE core.hosts ALTER COLUMN advertisement DROP NOT NULL;
ALTER TABLE core.hosts ALTER COLUMN exec_version DROP NOT NULL;
