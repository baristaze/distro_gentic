-- A knowledge entry names the project whose sessions reach it, or none for
-- every session of its tenant, and the slug an agent reads it by. The
-- previous release inserts without naming either for the minutes of the
-- roll, so both are nullable; an entry it wrote is the tenant's.

ALTER TABLE core.knowledge_entries
    ADD COLUMN project_id uuid,
    ADD COLUMN slug text;
CREATE INDEX ix_knowledge_entries_org_id_slug ON core.knowledge_entries (org_id, slug);

-- Each entry written so far takes its slug as the platform makes one: its
-- title's words, lowercase and hyphenated, then the last eight hex digits
-- of its id. The fence is lifted for this transaction alone, since the
-- migration login owns the table and FORCE binds the owner.
ALTER TABLE core.knowledge_entries NO FORCE ROW LEVEL SECURITY;
UPDATE core.knowledge_entries
SET slug = coalesce(
        nullif(
            trim(both '-' from left(
                trim(both '-' from regexp_replace(lower(title), '[^a-z0-9]+', '-', 'g')),
                71
            )),
            ''
        ),
        'entry'
    ) || '-' || right(replace(id::text, '-', ''), 8)
WHERE slug IS NULL;
ALTER TABLE core.knowledge_entries FORCE ROW LEVEL SECURITY;
