-- An exec item keeps when its host's claim last took it, by the platform's
-- clock, and the times its host sent with its result, while they agree
-- with that clock: the runner reads where the item's time went from them.
-- An item stored before this change keeps neither, and one a host of an
-- earlier release answers keeps no host times; the runner measures what
-- each one tells.

ALTER TABLE core.exec_items
    ADD COLUMN claimed_at timestamptz,
    ADD COLUMN host_times jsonb;
