"""Wire types of a tenant's tool policy: its layer of rules, who approves
each class of call, and the version a write names in `If-Match`."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from acme.om.context import Role
from acme.om.tools.types.policy import Decision
from acme.om.tools.types.tool import CLASS_NAME, TOOL_NAME, Effect
from acme.services.api.types.common import RequestBody, View

MAX_RULES = 200
MAX_TARGET = 20

TargetValue = str | int | bool


class PolicyRuleBody(RequestBody):
    """What a rule matches and what it decides. A selector left unset matches
    any call; every target attribute it names must equal the target's."""

    tool: str | None = Field(default=None, pattern=TOOL_NAME)
    authorization_class: str | None = Field(default=None, pattern=CLASS_NAME)
    effect: Effect | None = None
    target_kind: str | None = Field(default=None, min_length=1, max_length=64)
    target: dict[str, TargetValue] = Field(
        default_factory=dict[str, TargetValue], max_length=MAX_TARGET
    )
    decision: Decision


class PolicyRuleView(View):
    tool: str | None
    authorization_class: str | None
    effect: Effect | None
    target_kind: str | None
    target: dict[str, Any]
    decision: Decision


class ApproverRuleBody(RequestBody):
    """Who may approve a call of one class: people's roles, never a service."""

    authorization_class: str = Field(pattern=CLASS_NAME)
    roles: list[Role] = Field(min_length=1, max_length=len(Role))


class ApproverRuleView(View):
    authorization_class: str
    roles: list[Role]


class ToolPolicyRequest(RequestBody):
    """The tenant's whole layer, written over the version `If-Match` names."""

    rules: list[PolicyRuleBody] = Field(default_factory=list[PolicyRuleBody], max_length=MAX_RULES)
    approvers: list[ApproverRuleBody] = Field(
        default_factory=list[ApproverRuleBody], max_length=MAX_RULES
    )


class ToolPolicyView(View):
    """The tenant's layer; version 1 and empty until its first write."""

    rules: list[PolicyRuleView]
    approvers: list[ApproverRuleView]
    version: int
    updated_at: datetime
    updated_by: UUID
