-- Takes the hibernated warm VMs' columns back out.

ALTER TABLE core.pool_limits DROP COLUMN hibernated;
ALTER TABLE core.pool_vms DROP COLUMN hibernated_at;
ALTER TABLE core.pool_vms DROP COLUMN hibernates;
