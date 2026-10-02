"""The project a session belongs to: one row a session, keyed by the
session's id, written before the session and never rewritten. A session
spawned or handed over takes the row of the session it came from."""

from uuid import UUID

from acme.om.base import Created, Identifiable


class SessionProject(Identifiable, Created):
    """`id` is the session's own id; `project_id` its project, of the same
    tenant."""

    project_id: UUID
