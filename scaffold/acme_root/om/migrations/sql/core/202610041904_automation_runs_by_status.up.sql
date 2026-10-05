-- An automation's queued runs are read oldest first on every tick, and
-- counted at every admission. Its runs are never trimmed, so without the
-- status in the index each read walks the automation's whole run history.

CREATE INDEX ix_automation_runs_org_id_automation_id_status_created_at
    ON core.automation_runs (org_id, automation_id, status, created_at);
