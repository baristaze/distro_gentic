-- Takes the trust swimlane's rows back out: each fence, then its table.

DROP POLICY tenant_fence ON core.content_grants;
DROP TABLE core.content_grants;
DROP POLICY tenant_fence ON core.provider_keys;
DROP TABLE core.provider_keys;
DROP POLICY tenant_fence ON core.secret_declarations;
DROP TABLE core.secret_declarations;
