-- Takes the marker and the default back out. Each share keeps the
-- concurrency it holds, and a cap the sweep wrote stays in the queue.

ALTER TABLE core.fair_shares DROP COLUMN cap_carried;
ALTER TABLE core.fair_shares ALTER COLUMN concurrency DROP DEFAULT;
