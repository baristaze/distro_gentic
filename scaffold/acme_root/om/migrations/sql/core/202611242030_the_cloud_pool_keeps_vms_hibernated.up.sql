-- The cloud pool's hibernated warm VMs: a VM started to sleep, and since
-- when it sleeps, and how many its operators keep so.

ALTER TABLE core.pool_vms ADD COLUMN hibernates boolean DEFAULT false NOT NULL;
ALTER TABLE core.pool_vms ADD COLUMN hibernated_at timestamptz NULL;
ALTER TABLE core.pool_limits ADD COLUMN hibernated integer DEFAULT 0 NOT NULL;
