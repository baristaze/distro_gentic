-- The platform's index of the queue role goes, and the role is the
-- engine's.

DROP INDEX queue.ix_work_items_org_id_kind_target_id_created_at;
