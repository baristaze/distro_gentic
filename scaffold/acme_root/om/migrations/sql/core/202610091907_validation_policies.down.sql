-- Takes the validation policies back out: the fence, then the table.

DROP POLICY tenant_fence ON core.validation_policies;
DROP TABLE core.validation_policies;
