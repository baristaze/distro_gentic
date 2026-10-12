-- A session the sweep purges takes its notifications with it, one batch at
-- a time: the index bounds that read to the session's own rows, where the
-- list's index would walk every notification of the tenant.

CREATE INDEX ix_notifications_org_id_session_id ON core.notifications (org_id, session_id);
