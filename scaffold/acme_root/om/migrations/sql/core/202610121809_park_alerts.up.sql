-- A notification that a parked session waits on a person is a park
-- alert: the table and its indexes take the name, and every row stays.

ALTER TABLE core.notifications RENAME TO park_alerts;
ALTER TABLE core.park_alerts RENAME CONSTRAINT pk_notifications TO pk_park_alerts;
ALTER INDEX core.ix_notifications_org_id_recipient_created_at RENAME TO ix_park_alerts_org_id_recipient_created_at;
ALTER INDEX core.ix_notifications_org_id_session_id RENAME TO ix_park_alerts_org_id_session_id;
