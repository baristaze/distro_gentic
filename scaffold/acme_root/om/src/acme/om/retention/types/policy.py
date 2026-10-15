"""What a tenant declares about how long a session's content and its shape
are kept, and where; and what each agent project of the tenant narrows of it.

A tenant has one policy, changed by a compare-and-set on its version. An
agent project's narrowing only tightens: a session of the agent project takes the
tighter of the two, field by field (`retention.rules.tighter`), so no
agent project setting widens its tenant's policy. The one field two policies can
disagree on without one being tighter is the region, and an agent project that
names another region than its tenant's is refused."""

from datetime import timedelta
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.base import Identifiable, OmBase, Trackable
from acme.om.privacy.types.agent_session_privacy import StorageMode

REGION = r"^[a-z0-9][a-z0-9-]{0,31}$"
"""A region as a cloud names it, such as `eu-central-1`."""

MAX_AGENT_PROJECTS = 500
"""The narrowings one tenant's policy holds at most."""

MAX_LIFETIME = timedelta(days=36500)
"""The longest lifetime a policy is written with: a century. A lifetime is
added to a session's creation date, and a date has a last year. The write
refuses a lifetime past it (`retention.rules.past_bound`); the type does
not, so a stored row that holds one still reads."""


class RetentionPolicy(OmBase):
    """How long what a session says is kept (`content_lifetime`) and how long
    its shape is (`shape_lifetime`), both counted from the session's
    creation, None for no end; where its content may live
    (`storage_mode`: sealed at rest, or in a runtime's memory only); whether
    nothing it says may be kept anywhere, a provider included
    (`zero_retention`); and the region it is held to. Each default narrows
    nothing, so the default policy is the loosest there is."""

    content_lifetime: timedelta | None = Field(default=None, gt=timedelta(0))
    shape_lifetime: timedelta | None = Field(default=None, gt=timedelta(0))
    storage_mode: StorageMode = StorageMode.SEALED
    zero_retention: bool = False
    region: str | None = Field(default=None, pattern=REGION)

    @model_validator(mode="after")
    def _content_lives_within_its_shape(self) -> Self:
        if self.shape_lifetime is None:
            return self
        if self.content_lifetime is None or self.content_lifetime > self.shape_lifetime:
            raise ValueError("a session's content never outlives its shape")
        return self

    @model_validator(mode="after")
    def _zero_retention_keeps_nothing_at_rest(self) -> Self:
        if self.zero_retention and self.storage_mode is not StorageMode.MEMORY_ONLY:
            raise ValueError("zero retention keeps a session's content in memory only")
        return self


class AgentProjectRetention(OmBase):
    """What one agent project narrows of its tenant's policy. A field it leaves at
    its default narrows nothing."""

    agent_project_id: UUID
    policy: RetentionPolicy


class TenantRetention(Identifiable, Trackable):
    """The tenant's policy and its agent projects' narrowings, one record a
    tenant. Version 0 is the policy of a tenant that has declared none: the
    loosest, never stored."""

    policy: RetentionPolicy = RetentionPolicy()
    agent_projects: tuple[AgentProjectRetention, ...] = Field(
        default=(), max_length=MAX_AGENT_PROJECTS
    )
    version: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _one_narrowing_an_agent_project(self) -> Self:
        ids = [agent_project.agent_project_id for agent_project in self.agent_projects]
        if len(ids) != len(set(ids)):
            raise ValueError("an agent project narrows its tenant's policy once")
        return self

    def narrowing(self, agent_project_id: UUID | None) -> RetentionPolicy | None:
        """The agent project's narrowing, when the agent project has one."""
        if agent_project_id is None:
            return None
        return next(
            (p.policy for p in self.agent_projects if p.agent_project_id == agent_project_id), None
        )
