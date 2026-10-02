"""The projects swimlane's refusals, each in a shape of the platform's root."""

from acme.om.exceptions import Conflict, PlatformException


class ProjectsException(PlatformException): ...


class ProjectFixed(ProjectsException, Conflict):
    """A session's project is set when the session is created and never
    moves: another project was named for a session that has one, or one
    was named for a session created under none."""

    code = "project_fixed"
