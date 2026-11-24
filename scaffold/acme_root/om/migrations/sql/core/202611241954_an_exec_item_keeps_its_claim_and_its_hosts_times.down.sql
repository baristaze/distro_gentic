-- Takes an exec item's claim time and its host's times back out.

ALTER TABLE core.exec_items
    DROP COLUMN claimed_at,
    DROP COLUMN host_times;
