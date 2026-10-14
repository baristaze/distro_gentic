"""What the platform's runner suites share beside the engine's kind and
tool: the platform's software engineer on this host, the end-to-end suite's
kinds, and the turns that validate and submit a result."""

from uuid import uuid4

from runner_support import HOST, KINDS, SONNET

from acme.integrations.model_providers.calls import ModelReply
from acme.integrations.model_providers.content import ToolUseBlock
from acme.integrations.model_providers.types import StopReason, Usage
from acme.om.platform_agents import kinds
from acme.om.platform_agents.kinds import SOFTWARE_ENGINEER_KIND

SOFTWARE_ENGINEER = SOFTWARE_ENGINEER_KIND.model_copy(
    update={"version": SOFTWARE_ENGINEER_KIND.version + 1, "isolation": HOST}
)
"""The platform's software engineer, whole, in a directory on this host in place of
its container: its result is judged by the result gate."""

E2E_KINDS = (*KINDS, SOFTWARE_ENGINEER)
"""The end-to-end suite's kinds, which run beside the platform's own tools:
the assistant, and the software engineer."""


def validates(*, baseline: bool = False) -> ModelReply:
    """A turn that asks for a validation of the committed head, or, with
    `baseline`, for the baseline at the base."""
    asked = {"baseline": True} if baseline else {}
    use = ToolUseBlock(id=f"use_{uuid4().hex[:12]}", name=kinds.VALIDATE, input=asked)
    return ModelReply(
        blocks=(use,),
        stop_reason=StopReason.TOOL_USE,
        usage=Usage(input=140, output=10),
        model=SONNET,
    )


def submits(claim: str) -> ModelReply:
    """A turn that submits `claim`, citing the runs the last validation
    answered (the scripted twin's `$last_result.runs`)."""
    use = ToolUseBlock(
        id=f"use_{uuid4().hex[:12]}",
        name=kinds.SUBMIT_RESULT,
        input={"claim": claim, "evidence": "$last_result.runs"},
    )
    return ModelReply(
        blocks=(use,),
        stop_reason=StopReason.TOOL_USE,
        usage=Usage(input=180, output=15),
        model=SONNET,
    )
