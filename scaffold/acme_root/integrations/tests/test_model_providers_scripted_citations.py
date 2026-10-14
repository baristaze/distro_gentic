"""The scripted provider's citation: a scripted tool input that names a
field of the last tool result gets that field's value, and one the result
lacks stays as written. No test here reaches a network."""

from acme.integrations.model_providers.calls import Finished, Message, ModelCall, ModelReply
from acme.integrations.model_providers.content import (
    TextBlock,
    ThinkingBlock,
    ThinkingSource,
    ToolResultBlock,
    ToolUseBlock,
)
from acme.integrations.model_providers.scripted import ModelProviderScriptedImpl
from acme.integrations.model_providers.types import ProviderName, StopReason, Usage

CALL = ModelCall(
    model="claude-haiku-4-5",
    messages=(Message(role="user", blocks=(TextBlock(text="Why is the total missing?"),)),),
    max_output_tokens=1024,
)
SOURCE = ThinkingSource(provider=ProviderName.ANTHROPIC, model="claude-haiku-4-5")
REPLY = ModelReply(
    blocks=(
        TextBlock(text="Reading the import log before anything else."),
        ToolUseBlock(id="toolu_1", name="read_log", input={"path": "/var/log/import.log"}),
    ),
    thinking=(ThinkingBlock(text="The log first.", signature="sig", source=SOURCE),),
    stop_reason=StopReason.TOOL_USE,
    usage=Usage(input=120, cache_read=900, output=40, thinking=12),
    model="claude-haiku-4-5",
)


async def test_a_scripted_input_cites_a_field_of_the_last_tool_result() -> None:
    answered = Message(
        role="user",
        blocks=(
            ToolResultBlock(
                tool_use_id="toolu_1", parts=(TextBlock(text='{"runs": ["r1", "r2"]}'),)
            ),
        ),
    )
    call = CALL.model_copy(update={"messages": (*CALL.messages, answered)})
    citing = ToolUseBlock(
        id="toolu_2",
        name="submit_result",
        input={"evidence": "$last_result.runs", "note": "$last_result.absent", "claim": "ok"},
    )
    twin = ModelProviderScriptedImpl(
        ProviderName.ANTHROPIC, [REPLY.model_copy(update={"blocks": (citing,)})]
    )

    parts = [part async for part in twin.stream(call)]

    assert isinstance(parts[-1], Finished)
    (use,) = parts[-1].reply.blocks
    assert isinstance(use, ToolUseBlock)
    assert dict(use.input) == {
        "evidence": ("r1", "r2"),
        "note": "$last_result.absent",
        "claim": "ok",
    }
