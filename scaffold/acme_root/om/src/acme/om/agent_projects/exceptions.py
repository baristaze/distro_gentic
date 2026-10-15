"""The agent projects swimlane's refusals, each in a shape of the platform's root."""

from acme.om.exceptions import Conflict, OmException


class AgentProjectsException(OmException): ...


class AgentProjectFixed(AgentProjectsException, Conflict):
    """A session's agent project is set when the session is created and never
    moves: another agent project was named for a session that has one, or one
    was named for a session created under none."""

    code = "agent_project_fixed"


class AgentProjectInUse(AgentProjectsException, Conflict):
    """An agent project a session belongs to stays: its sessions read their
    policies and their work product through it."""

    code = "agent_project_in_use"
