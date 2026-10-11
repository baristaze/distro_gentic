-- Takes the findings and the recalls back out. The release before reads
-- neither.

DROP TABLE core.knowledge_recalls;
ALTER TABLE core.knowledge_entries DROP COLUMN findings;
ALTER TABLE core.playbooks DROP COLUMN findings;
