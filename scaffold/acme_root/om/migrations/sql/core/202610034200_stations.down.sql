-- Takes the stations back out: each fence, then each table.

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
