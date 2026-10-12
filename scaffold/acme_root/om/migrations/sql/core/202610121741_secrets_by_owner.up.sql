-- A secret's declaration is keyed by its owner too: each project declares
-- its own secret of a name. The reads walk the index by name, then owner.

DROP INDEX core.uq_secret_declarations_org_id_name;
CREATE UNIQUE INDEX uq_secret_declarations_org_id_name_owner
    ON core.secret_declarations (org_id, name, owner_kind, owner_id);
