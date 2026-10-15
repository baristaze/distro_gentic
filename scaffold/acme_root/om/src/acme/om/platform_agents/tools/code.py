"""The `code` toolset: change the files of a session's workspace, one place
at a time or whole, and run commands there, only through the call's
runtime. A path the agent project's validation policy protects is refused
before anyone is asked."""

from collections.abc import Callable
from datetime import timedelta
from typing import Self

from pydantic import Field, model_validator

from acme.om.base import Platform
from acme.om.context import TenantContext
from acme.om.evidence import EvidenceManagerInterface
from acme.om.evidence.rules import PATHS
from acme.om.exceptions import (
    ToolFailed,
)
from acme.om.platform_agents import kinds, rules
from acme.om.platform_agents.tools.base import MAX_PATH, MAX_READ, NativeToolImpl
from acme.om.steps.types.header import ToolFailure
from acme.om.tools.tool import ToolRuntime
from acme.om.tools.types.tool import Effect, ToolClass, ToolInput, ToolMode, ToolSpec

MAX_EDIT = MAX_READ  # bytes of a file one edit reads and writes back, at most


class WriteInput(ToolInput):
    path: str = Field(min_length=1, max_length=MAX_PATH)
    text: str


class Written(Platform):
    path: str
    size: int


class EditInput(ToolInput):
    """One place in a file: `old_text`, which must match exactly one place,
    or the lines `start_line` to `end_line`, counted from 1, both included."""

    path: str = Field(min_length=1, max_length=MAX_PATH)
    new_text: str = Field(max_length=MAX_EDIT)
    old_text: str | None = Field(default=None, min_length=1, max_length=MAX_EDIT)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _one_place(self) -> Self:
        by_lines = self.start_line is not None or self.end_line is not None
        if (self.old_text is not None) == by_lines:
            raise ValueError("an edit names old_text or a line range, never both")
        if by_lines and (
            self.start_line is None or self.end_line is None or self.start_line > self.end_line
        ):
            raise ValueError("a line range names start_line and end_line, the start first")
        return self


class Edited(Platform):
    path: str
    line: int  # where the new text starts
    lines: int  # how many lines the new text holds there
    size: int


class FileChangeImpl(NativeToolImpl):
    """A tool that changes one file of the workspace, by the path its input
    names. A path the policy of the session's agent project protects is refused at
    the call, before anyone is asked: the evidence reads it (`protection`)
    from the session's agent project, never from the input."""

    def __init__(self, evidence: Callable[[], EvidenceManagerInterface]) -> None:
        self._evidence = evidence

    async def preflight(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> None:
        # The engine asks a tool's target with no session, and the session's
        # agent project is what protects a path, so the refusal is made here.
        assert isinstance(call_input, WriteInput | EditInput)
        target = await self._evidence().protection(ctx, runtime.session_id, [call_input.path])
        if target.kind == PATHS and target.attributes.get("protected"):
            raise ToolFailed(
                ToolFailure.DENIED,
                f"{call_input.path} is protected by the agent project's validation policy: "
                "it is never changed by an agent",
            )


class WriteFileImpl(FileChangeImpl):
    """Writes one file of the workspace whole."""

    SPEC = ToolSpec(
        name=kinds.WRITE_FILE,
        description="Writes a text file of the workspace whole, creating it if it is missing.",
        input_model=WriteInput,
        output_model=Written,
        timeout=timedelta(seconds=30),
        authorization_class=ToolClass.WRITE,
        effect=Effect.IDEMPOTENT,
        interruptible=False,
        mode=ToolMode.SYNC,
    )

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, WriteInput)
        data = call_input.text.encode()
        await runtime.write_file(call_input.path, data)
        return Written(path=call_input.path, size=len(data))


class EditFileImpl(FileChangeImpl):
    """Replaces one place in a text file of the workspace and leaves the rest
    of it as it was. A match of more than one place is refused, so an edit
    never lands where the model did not mean. A repeat of a call could
    change a range twice, so a call whose run was lost is never run again."""

    SPEC = ToolSpec(
        name=kinds.EDIT_FILE,
        description=(
            "Replaces one place in a text file of the workspace with new_text, and leaves "
            "the rest of the file as it was. Name the place by old_text, copied exactly "
            "from the file, which must match one place only: a match of more than one is "
            "refused, so give more of the text around it. Or name it by start_line and "
            "end_line, counted from 1, both included. Answers the line the new text starts "
            "on and how many lines it holds."
        ),
        input_model=EditInput,
        output_model=Edited,
        timeout=timedelta(seconds=30),
        authorization_class=ToolClass.WRITE,
        effect=Effect.UNSAFE,
        interruptible=False,
        mode=ToolMode.SYNC,
    )

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, EditInput)
        path = call_input.path
        data = await runtime.read_file(path, MAX_EDIT + 1)
        if len(data) > MAX_EDIT:
            raise ToolFailed(
                ToolFailure.PERMANENT,
                f"{path} is past the {MAX_EDIT:,} bytes an edit takes: write it whole",
            )
        try:
            text = data.decode()
        except UnicodeDecodeError:
            raise ToolFailed(ToolFailure.PERMANENT, f"{path} is not UTF-8 text") from None
        edit = rules.edited(
            text,
            call_input.new_text,
            old_text=call_input.old_text,
            start_line=call_input.start_line,
            end_line=call_input.end_line,
        )
        if isinstance(edit, str):
            raise ToolFailed(ToolFailure.PERMANENT, f"{path}: {edit}")
        written = edit.text.encode()
        await runtime.write_file(path, written)
        return Edited(path=path, line=edit.line, lines=edit.lines, size=len(written))


class CommandInput(ToolInput):
    argv: tuple[str, ...] = Field(min_length=1)


class CommandOutput(Platform):
    exit_code: int | None
    stdout: str
    stderr: str


class RunCommandImpl(NativeToolImpl):
    SPEC = ToolSpec(
        name=kinds.RUN_COMMAND,
        description=(
            "Runs one command in the workspace, as an argument vector, and answers its exit "
            "code and what it printed."
        ),
        input_model=CommandInput,
        output_model=CommandOutput,
        timeout=timedelta(minutes=10),
        authorization_class=ToolClass.EXECUTE,
        effect=Effect.UNSAFE,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, CommandInput)
        result = await runtime.run(call_input.argv)
        return CommandOutput(exit_code=result.exit_code, stdout=result.stdout, stderr=result.stderr)
