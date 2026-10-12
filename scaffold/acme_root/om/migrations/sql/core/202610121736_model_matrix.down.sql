-- Takes the model matrix back out: the fences, then the tables.

DROP POLICY tenant_fence ON core.fill_overrides;
DROP POLICY tenant_fence ON core.matrix_pins;
DROP TABLE core.fill_overrides;
DROP TABLE core.matrix_pins;
DROP TABLE core.model_retirements;
DROP TABLE core.benchmark_results;
DROP TABLE core.matrix_versions;
