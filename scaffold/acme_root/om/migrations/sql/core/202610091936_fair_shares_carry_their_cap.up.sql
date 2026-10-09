-- How many of a tenant's loops run at once is the work queue's cap on its
-- lane, so a share holds its plan tier and its own lane alone. The release
-- before still reads `concurrency`, so the column stays for it, and a row
-- written without one takes the default share. `cap_carried` is false on
-- every row there is, and on a row the release before writes: the sweep
-- writes its concurrency as the tenant's own cap on its lane, then marks it.

ALTER TABLE core.fair_shares ALTER COLUMN concurrency SET DEFAULT 8;
ALTER TABLE core.fair_shares ADD COLUMN cap_carried boolean NOT NULL DEFAULT false;
