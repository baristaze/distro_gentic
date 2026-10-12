-- Takes the pins and the mark back out. The release before reads neither.

ALTER TABLE core.playbook_invocations DROP COLUMN pinned;
DROP TABLE core.playbook_pins;
