"""A draft of the tenant's tool policy: what the assistant proposes, checked
against what the tenant holds, and the difference from what is live. A
draft changes nothing. A person applies it by writing the policy it holds
at the version it was drawn from."""

from typing import Self

from pydantic import Field, model_validator

from acme.om.base import Platform
from acme.om.tools.types.policy import ApproverRule, PolicyRule


class PolicyDraft(Platform):
    """`based_on` is the live policy's version the draft was drawn from; the
    write that applies it names that version, so a policy changed since is
    refused rather than overwritten. `problems` is empty when the draft is
    valid."""

    based_on: int = Field(ge=1)
    valid: bool
    problems: tuple[str, ...] = ()
    added: tuple[PolicyRule, ...] = ()
    removed: tuple[PolicyRule, ...] = ()
    approvers_before: tuple[ApproverRule, ...] = ()
    approvers_after: tuple[ApproverRule, ...] = ()
    rules: tuple[PolicyRule, ...] = ()

    @model_validator(mode="after")
    def _valid_has_no_problem(self) -> Self:
        if self.valid == bool(self.problems):
            raise ValueError("a draft is valid exactly when it names no problem")
        return self
