"""Acceptance hides its suite: no surface the agent reads may mention it,
and a scanner checks every one."""

from enum import StrEnum

from pydantic import Field

from acme.om.base import Platform


class Surface(StrEnum):
    """Every kind of text an agent reads. A scan covers each of them."""

    PROMPT = "prompt"
    KNOWLEDGE = "knowledge"
    TOOL_SOURCE = "tool_source"
    EVIDENCE = "evidence"
    PULL_REQUEST = "pull_request"


class Leak(Platform):
    """A mention of the hidden suite where the agent can read it: the
    surface, the item in it, and the marker it holds."""

    surface: Surface
    item: str = Field(min_length=1)
    marker: str = Field(min_length=1)
