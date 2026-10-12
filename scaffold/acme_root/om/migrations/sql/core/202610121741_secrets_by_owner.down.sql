-- Takes the owner back out of a declaration's key. It fails, and changes
-- nothing, while two owners of a tenant each declare one name.

DROP INDEX core.uq_secret_declarations_org_id_name_owner;
CREATE UNIQUE INDEX uq_secret_declarations_org_id_name ON core.secret_declarations (org_id, name);
