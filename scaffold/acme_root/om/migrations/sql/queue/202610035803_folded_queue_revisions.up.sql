-- The platform's index of the queue role, on the engine's: work items by
-- tenant, kind, and target, newest first. A read of whether a target has
-- an item open, or of its latest item of a kind, takes it, per workspace
-- event and per binding on every pass of the session runner's sweep.

CREATE INDEX ix_work_items_org_id_kind_target_id_created_at ON queue.work_items (org_id, kind, target_id, created_at);
