"""Intake's kind of work, named here as a namespace names its own
(`work.kinds`). The business root registers it below the marker of
`root.KINDS`, so it is no line in a list the scaffold writes."""

from enum import StrEnum

from acme.om.base import OmBase
from acme.om.context import Permission
from acme.om.work.kinds import WorkKindSpec


class IntakeWorkKind(StrEnum):
    """The names of intake's kinds of work."""

    MEMBER_LEFT = "MEMBER_LEFT"  # what the tenant keeps of a person who left it


class MemberLeftPayload(OmBase):
    """The MEMBER_LEFT kind carries nothing: its target is the user whose
    place in the tenant ended, by a member's removal or an account's
    deletion, and that id is all the work needs."""


INTAKE_WORK_KINDS: tuple[WorkKindSpec, ...] = (
    # A member's removal and an account's deletion ask for this one, each
    # relayed from its own commit; no route enqueues it. Unlinking another
    # person's account manages members.
    WorkKindSpec(IntakeWorkKind.MEMBER_LEFT, MemberLeftPayload, Permission.MANAGE_MEMBERS),
)
"""Intake's kinds, each with its payload, the permission that asks for it,
and its lane."""
