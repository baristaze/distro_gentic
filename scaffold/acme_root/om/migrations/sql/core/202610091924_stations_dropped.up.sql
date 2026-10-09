-- Takes the stations out: the secrets declared on a station, then each
-- fence, then each table. Their rows go with them, and nothing brings
-- them back. The fence binds the owner and a migration names no tenant,
-- so it is lifted for the one delete and put back, in the migration's
-- transaction.

ALTER TABLE core.secret_declarations NO FORCE ROW LEVEL SECURITY;
DELETE FROM core.secret_declarations WHERE owner_kind = 'station';
ALTER TABLE core.secret_declarations FORCE ROW LEVEL SECURITY;

DROP POLICY tenant_fence ON core.station_jobs;
DROP POLICY tenant_fence ON core.station_leases;
DROP POLICY tenant_fence ON core.station_line_entries;
DROP POLICY tenant_fence ON core.daemon_credentials;
DROP POLICY tenant_fence ON core.stations;
DROP POLICY tenant_fence ON core.station_pools;
DROP POLICY tenant_fence ON core.labs;
DROP TABLE core.station_jobs;
DROP TABLE core.station_leases;
DROP TABLE core.station_line_entries;
DROP TABLE core.daemon_credentials;
DROP TABLE core.stations;
DROP TABLE core.station_pools;
DROP TABLE core.labs;
