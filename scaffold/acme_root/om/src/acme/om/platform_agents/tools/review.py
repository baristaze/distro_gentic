"""The `review` toolset: read a pull request, its checks, and its files at
its head through the forge's integration, only through an installation the
session's tenant connected; note each finding, checked against the file it
lands in, and submit the review. Nothing they do writes."""

import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from acme.infra.exceptions import InfraException
from acme.integrations.events import IntegrationInterface, PullRequestRead
from acme.integrations.exceptions import ProviderRefused
from acme.om.agent_steps.types.content import MAX_NAME
from acme.om.agent_steps.types.header import ToolFailure
from acme.om.agent_workspaces.rules import COMMIT
from acme.om.base import OmBase
from acme.om.context import TenantContext
from acme.om.exceptions import (
    ToolFailed,
)
from acme.om.intake import IntakeManagerInterface
from acme.om.intake.tools import FORGE, connected
from acme.om.platform_agents import kinds, rules
from acme.om.platform_agents.tools.base import (
    MAX_PATH,
    MAX_READ,
    ONE_LINE,
    NativeToolImpl,
    ResultInput,
    Text,
)
from acme.om.tools.rules import bounded
from acme.om.tools.tool import ToolRuntime
from acme.om.tools.types.tool import Effect, ToolClass, ToolInput, ToolMode, ToolSpec

MAX_VIEW = 45_000
"""Characters of one read of a pull request, at most, as the model reads it
in JSON: inside what the engine lets the model read of one answer
(50,000), so nothing of it is cut, its id and its head least of all."""
MAX_BODY = 10_000  # characters of a pull request's body a read answers, its head and its tail
MAX_FINDING = 4_000  # characters of what one finding says


class PullRequestAddress(ToolInput):
    on: str = Field(min_length=1, max_length=MAX_NAME, pattern=ONE_LINE)


class ReviewedFile(OmBase):
    path: str
    status: str
    patch: str | None = None  # None: the forge shows none, or the bound left it out


class Check(OmBase):
    name: str
    status: str
    conclusion: str | None = None


class PullRequestView(OmBase):
    """A pull request as the forge holds it, read for a review: the id a
    review cites for this read, its head, the files it changes with their
    patches, and its checks, within `MAX_VIEW`. The fields a review cites
    and the counts come first, so the head of a long answer, which is what
    the window shows of it at once, holds them."""

    id: UUID
    on: str
    head: str
    complete: bool  # every file it changes is listed
    files_left_out: int  # files it changes the bound left off the list
    patches_left_out: int  # listed files whose patch the bound left out
    url: str
    title: str
    state: str
    head_ref: str
    base_ref: str
    body: str
    checks: tuple[Check, ...]
    files: tuple[ReviewedFile, ...]


def _chars(value: Any) -> int:
    """The characters of `value` as the model reads it: JSON, as the engine
    writes an answer."""
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def view_of(key: UUID, read: PullRequestRead) -> PullRequestView:
    """A read of a pull request as the model reads it, within `MAX_VIEW`:
    each field whole but the body, cut to `MAX_BODY`; then the files it
    changes, in the forge's order, listed while the answer fits; then each
    listed file's patch while it still fits. Whatever the bound leaves out
    is counted, never cut."""
    changed = read.files
    bare = PullRequestView(
        id=key,
        on=read.address,
        url=read.url,
        title=read.title,
        body=bounded(read.body, MAX_BODY),
        state=read.state,
        head=read.head,
        head_ref=read.head_ref,
        base_ref=read.base_ref,
        files=(),
        complete=False,
        # The most each count can be, so the size measured is the most the
        # answer can be.
        files_left_out=len(changed),
        patches_left_out=len(changed),
        checks=tuple(
            Check(name=c.name, status=c.status, conclusion=c.conclusion) for c in read.checks
        ),
    )
    left = MAX_VIEW - _chars(bare.model_dump(mode="json"))
    listed: list[ReviewedFile] = []
    for file in changed:
        entry = ReviewedFile(path=file.path, status=file.status)
        cost = _chars(entry.model_dump(mode="json")) + len(",")
        if cost > left:
            break
        listed.append(entry)
        left -= cost
    patches_left_out = 0
    for at, file in enumerate(changed[: len(listed)]):
        if file.patch is None:
            continue
        cost = _chars(file.patch) - _chars(None)
        if cost > left:
            patches_left_out += 1
            continue
        listed[at] = listed[at].model_copy(update={"patch": file.patch})
        left -= cost
    return bare.model_copy(
        update={
            "files": tuple(listed),
            "complete": read.complete and len(listed) == len(changed),
            "files_left_out": len(changed) - len(listed),
            "patches_left_out": patches_left_out,
        }
    )


def forge_failure(failed: InfraException, doing: str) -> ToolFailed:
    """The failure the model reads when the forge refused, or could not
    answer, a read."""
    failure = (
        ToolFailure.PERMANENT if isinstance(failed, ProviderRefused) else ToolFailure.TRANSIENT
    )
    return ToolFailed(failure, f"the forge did not answer {doing}: {failed.message}")


def citable(failed: ToolFailed, key: UUID) -> ToolFailed:
    """A read or a finding of a review that failed, as the model reads it:
    its failure, and the id of the call, which a failed review cites to say
    why it could not review."""
    return ToolFailed(
        failed.failure, f"{failed.message} (this call's id, which submit_review cites: {key})"
    )


class ReadPullRequestImpl(NativeToolImpl):
    """Reads a pull request through the forge's integration, through an
    installation the session's tenant connected, and changes nothing: its
    head, the files it changes with their patches, and the checks at its
    head, within what the model reads of one answer (`view_of`). Its id is
    the call's own, which a review cites, and a read that fails names it
    too."""

    SPEC = ToolSpec(
        name=kinds.READ_PULL_REQUEST,
        description=(
            "Reads a pull request of the forge, named as owner/repo#12: its title and body, "
            "its state, its head commit, the files it changes with their patches, and the "
            "checks at its head. Files and patches are listed while they fit one answer; "
            "files_left_out and patches_left_out count the rest. Answers an id, which "
            "submit_review cites; a read that fails names its id too."
        ),
        input_model=PullRequestAddress,
        output_model=PullRequestView,
        timeout=timedelta(seconds=60),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(
        self,
        intake: Callable[[], IntakeManagerInterface],
        integrations: Callable[[str], IntegrationInterface],
    ) -> None:
        self._intake = intake
        self._integrations = integrations

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> OmBase:
        assert isinstance(call_input, PullRequestAddress)
        forge = self._integrations(FORGE)
        try:
            installation = await connected(ctx, self._intake(), forge, call_input.on)
            try:
                read = await forge.read_pull_request(call_input.on, installation=installation)
            except InfraException as failed:
                raise forge_failure(failed, f"a read of {call_input.on}") from None
        except ToolFailed as failed:
            raise citable(failed, runtime.key) from None
        return view_of(runtime.key, read)


class FileAtHeadInput(PullRequestAddress):
    path: str = Field(min_length=1, max_length=MAX_PATH, pattern=ONE_LINE)
    # The head read_pull_request answered: a commit's full id, nothing else.
    head: str = Field(pattern=rf"^(?:{COMMIT.pattern})$")

    @field_validator("path")
    @classmethod
    def _a_path_of_the_repository(cls, path: str) -> str:
        refusal = rules.path_refusal(path)
        if refusal is not None:
            raise ValueError(refusal)
        return path


async def file_at(
    ctx: TenantContext,
    intake: IntakeManagerInterface,
    forge: IntegrationInterface,
    at: FileAtHeadInput,
) -> str:
    """The text of the file `at` names, read through the forge at the head
    it names, its first `MAX_READ` bytes; a file that is not text fails."""
    installation = await connected(ctx, intake, forge, at.on)
    try:
        data = await forge.read_file(at.on, at.path, at.head, installation=installation)
    except InfraException as failed:
        raise forge_failure(failed, f"a read of {at.path} at {at.head}") from None
    try:
        return data[:MAX_READ].decode()
    except UnicodeDecodeError:
        raise ToolFailed(ToolFailure.PERMANENT, f"{at.path} is not text") from None


class FileAtHead(OmBase):
    """A file of a pull request's repository at its head, read for a
    review: the id a review cites for this read, and its text."""

    id: UUID
    text: str


class ReadPullRequestFileImpl(NativeToolImpl):
    """Reads one file of a pull request's repository at the head a read of
    it answered, through the forge, as `read_pull_request` reads: a review
    reads the branch at its head without a workspace of its own. Its id is
    the call's own, which a review cites, and a read that fails names it
    too."""

    SPEC = ToolSpec(
        name=kinds.READ_PULL_REQUEST_FILE,
        description=(
            "Reads a text file of a pull request's repository at its head, its first 200,000 "
            "bytes: `on` names the pull request, `path` the file from the repository's root, "
            "and `head` the head commit read_pull_request answered. Answers an id, which "
            "submit_review cites; a read that fails names its id too."
        ),
        input_model=FileAtHeadInput,
        output_model=FileAtHead,
        timeout=timedelta(seconds=30),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(
        self,
        intake: Callable[[], IntakeManagerInterface],
        integrations: Callable[[str], IntegrationInterface],
    ) -> None:
        self._intake = intake
        self._integrations = integrations

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> OmBase:
        assert isinstance(call_input, FileAtHeadInput)
        forge = self._integrations(FORGE)
        try:
            text = await file_at(ctx, self._intake(), forge, call_input)
        except ToolFailed as failed:
            raise citable(failed, runtime.key) from None
        return FileAtHead(id=runtime.key, text=text)


class FindingInput(FileAtHeadInput):
    line: int = Field(ge=1)
    grade: Literal["high", "medium", "low"]
    text: str = Field(min_length=1, max_length=MAX_FINDING)


class Finding(OmBase):
    """A finding as it was noted: the id a review cites for it, and where it
    lands."""

    id: UUID
    on: str
    path: str
    line: int
    head: str
    grade: str
    text: str


class NoteFindingImpl(NativeToolImpl):
    """Notes one finding of a review: a line of a file of the pull request's
    repository at its head, a grade, and what is wrong. The file is read at
    that head through the forge first, so a finding lands on a line that is
    there; one that names no file, or a line past its end, is refused. It
    writes nothing outside the session's history. Its id is the call's own,
    which a review cites, and a finding that fails names it too."""

    SPEC = ToolSpec(
        name=kinds.NOTE_FINDING,
        description=(
            "Notes one finding of your review: `on` the pull request, `path` the file from the "
            "repository's root, `head` the head commit read_pull_request answered, `line` its "
            "line there, counted from 1, `grade` high, medium, or low, and `text` what is wrong "
            "and what it does in real use. Answers an id, which submit_review cites; a "
            "finding that fails names its id too."
        ),
        input_model=FindingInput,
        output_model=Finding,
        timeout=timedelta(seconds=30),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(
        self,
        intake: Callable[[], IntakeManagerInterface],
        integrations: Callable[[str], IntegrationInterface],
    ) -> None:
        self._intake = intake
        self._integrations = integrations

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> OmBase:
        assert isinstance(call_input, FindingInput)
        forge = self._integrations(FORGE)
        try:
            text = await file_at(ctx, self._intake(), forge, call_input)
            refusal = rules.line_refusal(call_input.path, text, call_input.line)
            if refusal is not None:
                raise ToolFailed(ToolFailure.INVALID_INPUT, refusal)
        except ToolFailed as failed:
            raise citable(failed, runtime.key) from None
        return Finding(
            id=runtime.key,
            on=call_input.on,
            path=call_input.path,
            line=call_input.line,
            head=call_input.head,
            grade=call_input.grade,
            text=call_input.text,
        )


class SubmitReviewImpl(NativeToolImpl):
    """The reviewer's result tool. The loop judges what is submitted through
    the result gate, which reads the reads and the findings the review
    cites, so the tool itself never runs."""

    SPEC = ToolSpec(
        name=kinds.SUBMIT_REVIEW,
        description=(
            "Submits your review: succeeded once every finding is noted, or none was found, "
            "failed when you could not review the pull request. `evidence` is the ids "
            "read_pull_request, read_pull_request_file, and note_finding answered, or named "
            "when they failed: a success cites the read of the pull request and every finding; "
            "a failure cites the reads that failed and show why."
        ),
        input_model=ResultInput,
        output_model=Text,
        timeout=timedelta(seconds=30),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=False,
        mode=ToolMode.SYNC,
    )

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> OmBase:
        raise ToolFailed(ToolFailure.PERMANENT, "a review is judged by the loop, never run")
