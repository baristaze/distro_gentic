-- Takes the connectors and the sessions' pins back out. The release before
-- reads neither.

DROP TABLE core.session_connectors;
DROP TABLE core.connectors;
