-- The release before reads the names it wrote. Every row stays.

ALTER TABLE core.park_alerts RENAME CONSTRAINT pk_park_alerts TO pk_notifications;
ALTER INDEX core.ix_park_alerts_org_id_recipient_created_at RENAME TO ix_notifications_org_id_recipient_created_at;
ALTER INDEX core.ix_park_alerts_org_id_session_id RENAME TO ix_notifications_org_id_session_id;
ALTER TABLE core.park_alerts RENAME TO notifications;
