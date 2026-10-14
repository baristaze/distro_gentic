"""The agent project a session belongs to: one row a session, keyed by the
session's id, written before the session and never rewritten. A session
spawned or handed over takes the row of the session it came from."""

from uuid import UUID

from acme.om.base import Created, Identifiable


class SessionAgentProject(Identifiable, Created):
    """`id` is the session's own id; `agent_project_id` its agent project, of the same
    tenant."""

    agent_project_id: UUID
