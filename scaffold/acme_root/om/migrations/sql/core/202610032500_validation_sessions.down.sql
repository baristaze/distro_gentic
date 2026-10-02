-- Takes the validation sessions back out: the fence, then the table.

DROP POLICY tenant_fence ON core.validation_sessions;
DROP TABLE core.validation_sessions;
