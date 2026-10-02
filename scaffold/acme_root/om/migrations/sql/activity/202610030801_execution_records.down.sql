-- Takes the runs, the validations, and the hypotheses and findings back
-- out: each fence, then each table.

DROP POLICY tenant_fence ON activity.inferences;
DROP TABLE activity.inferences;
DROP POLICY tenant_fence ON activity.validations;
DROP TABLE activity.validations;
DROP POLICY tenant_fence ON activity.execution_records;
DROP TABLE activity.execution_records;
