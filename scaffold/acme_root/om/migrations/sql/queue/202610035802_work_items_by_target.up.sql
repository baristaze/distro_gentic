-- Whether a target has an item open, and its latest item of a kind, are
-- read by tenant, kind, and target, newest first: per workspace event, and
-- per binding on every pass of the session runner's sweep. Without this
-- index each read filters the tenant's whole work history.

CREATE INDEX ix_work_items_org_id_kind_target_id_created_at
    ON queue.work_items (org_id, kind, target_id, created_at);
