-- Deletes the station items: no claimant takes one. The fence binds the
-- owner and a migration names no tenant, so it is lifted for the one
-- delete and put back, in the migration's transaction. The schema does
-- not change.

ALTER TABLE queue.work_items NO FORCE ROW LEVEL SECURITY;
DELETE FROM queue.work_items WHERE kind = 'STATION';
ALTER TABLE queue.work_items FORCE ROW LEVEL SECURITY;
