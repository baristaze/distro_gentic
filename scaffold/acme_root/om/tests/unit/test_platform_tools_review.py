"""The `review` toolset's tools, over memory: the reviewer reads a
recorded pull request through the forge, notes its findings with file and
line, and delivers its review through its result tool. A read that fails
names its id for the review to cite, and a pull request too large for one
answer keeps its id and its head whole."""

import json
import re
from pathlib import Path
from uuid import UUID

import pytest
from unit.platform_tools import CART, RECORDED, REVIEWED, REVIEWED_HEAD, reviewing

from acme.integrations.events import ChangedFile
from acme.integrations.events.twin import IntegrationTwinImpl, twin_installation
from acme.integrations.model_providers.calls import ModelCall, ModelReply
from acme.om.agent_steps.types.content import TextBlock, ToolResultBlock
from acme.om.agent_steps.types.header import LoopOutcome, ToolFailure, ToolResponseHeader
from acme.om.agents.types.result import Claim
from acme.om.base import new_id
from acme.om.intake.tools import FORGE
from acme.om.platform_agents import kinds
from acme.om.platform_agents.tools.review import MAX_VIEW

from contracts.loops import reply, said
from contracts.platform_agents import Later, Platform, calls, platform_over


def submitting(claim: Claim) -> Later:
    """The reviewer's turn that submits its review, citing every id its
    reads and its findings answered."""

    def turn(call: ModelCall) -> ModelReply:
        cited: list[str] = []
        for message in call.messages:
            for block in message.blocks:
                if not isinstance(block, ToolResultBlock):
                    continue
                for part in block.parts:
                    if isinstance(part, TextBlock) and part.text.startswith("{"):
                        found = json.loads(part.text).get("id")
                        if found is not None:
                            cited.append(found)
        return reply(calls(kinds.SUBMIT_REVIEW, "use_review", claim=claim.value, evidence=cited))

    return turn


NAMED_ID = re.compile(r"submit_review cites: ([0-9a-f-]{36})")
"""The id a failed read of a review names, which a failed review cites."""


def giving_up(reason: str) -> Later:
    """The reviewer's turn that says why it could not review, and submits
    the review as failed, citing the id each failed read named."""

    def turn(call: ModelCall) -> ModelReply:
        cited = [
            found
            for message in call.messages
            for block in message.blocks
            if isinstance(block, ToolResultBlock)
            for part in block.parts
            if isinstance(part, TextBlock)
            for found in NAMED_ID.findall(part.text)
        ]
        return reply(
            said(reason),
            calls(kinds.SUBMIT_REVIEW, "use_review", claim=Claim.FAILED.value, evidence=cited),
        )

    return turn


async def test_a_reviewer_answers_its_findings_with_file_and_line_through_its_result_tool(
    tmp_path: Path,
) -> None:
    platform, forge = await reviewing(tmp_path)
    agent_session_id = await platform.start(kinds.REVIEWER)
    await platform.say(agent_session_id, f"Review {REVIEWED}.")
    platform.anthropic.add(
        reply(calls(kinds.READ_PULL_REQUEST, "use_read", on=REVIEWED)),
        reply(
            calls(
                kinds.READ_PULL_REQUEST_FILE,
                "use_file",
                on=REVIEWED,
                path="src/cart.py",
                head=REVIEWED_HEAD,
            ),
            calls(
                kinds.NOTE_FINDING,
                "use_finding",
                on=REVIEWED,
                path="src/cart.py",
                head=REVIEWED_HEAD,
                line=3,
                grade="high",
                text="An empty cart divides by zero, so its total raises.",
            ),
        ),
        submitting(Claim.SUCCEEDED),
    )

    run = await platform.managers.loop.run(platform.owner, agent_session_id)

    assert run.outcome is LoopOutcome.SUCCEEDED
    # It asks XL of its main role: the size's model reviews.
    assert platform.anthropic.calls[0].model == "claude-opus-5-5"
    failure, text = await platform.answer(agent_session_id, "use_read")
    read = json.loads(text)
    assert failure is None
    assert (read["on"], read["head"]) == (REVIEWED, REVIEWED_HEAD)
    assert [(f["path"], f["patch"] is not None) for f in read["files"]] == [("src/cart.py", True)]
    assert read["checks"] == [{"name": "unit", "status": "completed", "conclusion": "failure"}]
    _, text = await platform.answer(agent_session_id, "use_file")
    assert json.loads(text)["text"] == CART
    failure, text = await platform.answer(agent_session_id, "use_finding")
    finding = json.loads(text)
    assert failure is None
    assert (finding["path"], finding["line"], finding["head"], finding["grade"]) == (
        "src/cart.py",
        3,
        REVIEWED_HEAD,
        "high",
    )
    # The review is accepted, verified: the gate read the read and the
    # finding it cites in the session's own history.
    failure, text = await platform.answer(agent_session_id, "use_review")
    assert failure is None and "accepted, verified" in text
    assert UUID(finding["id"]) != UUID(read["id"])
    # The forge was read, and nothing was written to it.
    assert forge.posted == [] and forge.refs == {} and forge.pull_requests == []


async def test_a_finding_off_the_file_and_a_review_citing_no_read_are_refused(
    tmp_path: Path,
) -> None:
    platform, _ = await reviewing(tmp_path)
    agent_session_id = await platform.start(kinds.REVIEWER)
    await platform.say(agent_session_id, f"Review {REVIEWED}.")
    at = {"on": REVIEWED, "head": REVIEWED_HEAD, "grade": "low", "text": "Name it."}
    platform.anthropic.add(
        reply(
            calls(kinds.NOTE_FINDING, "use_past", path="src/cart.py", line=40, **at),
            calls(kinds.NOTE_FINDING, "use_out", path="../secrets.txt", line=1, **at),
            calls(kinds.NOTE_FINDING, "use_kept", path="src/cart.py", line=1, **at),
        ),
        # A success that cites a finding and no read of the pull request.
        submitting(Claim.SUCCEEDED),
        reply(
            calls(
                kinds.SUBMIT_REVIEW,
                "use_made_up",
                claim="succeeded",
                evidence=[str(new_id())],
            )
        ),
        reply(said("I could not review it.")),
    )

    await platform.managers.loop.run(platform.owner, agent_session_id)

    failure, text = await platform.answer(agent_session_id, "use_past")
    assert failure is ToolFailure.INVALID_INPUT and "holds 3 lines" in text
    failure, _ = await platform.answer(agent_session_id, "use_out")
    assert failure is ToolFailure.INVALID_INPUT
    failure, _ = await platform.answer(agent_session_id, "use_kept")
    assert failure is None
    failure, text = await platform.answer(agent_session_id, "use_review")
    assert failure is ToolFailure.DENIED and "its read of the pull request" in text
    failure, text = await platform.answer(agent_session_id, "use_made_up")
    assert failure is ToolFailure.DENIED and "names no read or finding of this session" in text


async def test_a_reviewers_malformed_input_is_refused_before_anything_is_read(
    tmp_path: Path,
) -> None:
    platform, _ = await reviewing(tmp_path)
    agent_session_id = await platform.start(kinds.REVIEWER)
    await platform.say(agent_session_id, f"Review {REVIEWED}.")
    at = {"on": REVIEWED, "head": REVIEWED_HEAD, "grade": "low", "text": "Name it."}
    platform.anthropic.add(
        reply(
            calls(
                kinds.NOTE_FINDING,
                "use_ref",
                path="src/cart.py",
                line=1,
                **{**at, "head": f"x{REVIEWED_HEAD}"},
            ),
            calls(kinds.NOTE_FINDING, "use_zero", path="src/cart.py", line=0, **at),
            calls(
                kinds.NOTE_FINDING,
                "use_grade",
                path="src/cart.py",
                line=1,
                **{**at, "grade": "blocker"},
            ),
            calls(kinds.READ_PULL_REQUEST, "use_lines", on=f"{REVIEWED}\nacme/other#1"),
        ),
        reply(said("I could not read it.")),
    )

    await platform.managers.loop.run(platform.owner, agent_session_id)

    for malformed in ("use_ref", "use_zero", "use_grade", "use_lines"):
        failure, _ = await platform.answer(agent_session_id, malformed)
        assert failure is ToolFailure.INVALID_INPUT, malformed


@pytest.mark.parametrize(
    ("connects", "on", "failure", "why"),
    [
        # Of a tenant that connected no installation of the forge.
        (False, REVIEWED, ToolFailure.DENIED, "no installation of the forge this tenant connected"),
        # A pull request the forge does not hold.
        (True, "acme/widgets#99", ToolFailure.PERMANENT, "holds no pull request acme/widgets#99"),
    ],
)
async def test_a_reviewer_that_cannot_read_its_pull_request_fails_citing_that_read(
    tmp_path: Path, connects: bool, on: str, failure: ToolFailure, why: str
) -> None:
    forge = IntegrationTwinImpl(FORGE)
    forge.record_pull_request(RECORDED, {"src/cart.py": CART.encode()})
    platform = platform_over(tmp_path, forge=forge)
    if connects:
        await platform.connect(FORGE, twin_installation("acme"))
    agent_session_id = await platform.start(kinds.REVIEWER)
    await platform.say(agent_session_id, f"Review {on}.")
    reason = f"I could not review {on}: the forge would not read it to me."
    platform.anthropic.add(
        reply(calls(kinds.READ_PULL_REQUEST, "use_read", on=on)),
        giving_up(reason),
    )

    run = await platform.managers.loop.run(platform.owner, agent_session_id)

    read_failure, text = await platform.answer(agent_session_id, "use_read")
    assert read_failure is failure and why in text
    # The failed read names its id, the review cites it, and the gate finds
    # it among the session's own reads: the run ends failed at once, with
    # its reason, after no more calls than the read and the review.
    (named,) = NAMED_ID.findall(text)
    review_failure, verdict = await platform.answer(agent_session_id, "use_review")
    assert review_failure is None and "accepted, verified" in verdict
    assert run.outcome is LoopOutcome.FAILED
    assert len(platform.anthropic.calls) == 2
    history = await platform.history(agent_session_id)
    assert reason in [step.as_text() for step in history]
    assert UUID(named) in {step.id for step in history}
    assert forge.posted == []


async def kept_whole(platform: Platform, agent_session_id: UUID, use_id: str) -> tuple[str, str]:
    """What the window shows at once of a long answer to the call `use_id`,
    its head, and the whole answer it keeps as an artifact."""
    for step in await platform.history(agent_session_id):
        header = step.header
        if not isinstance(header, ToolResponseHeader) or header.artifact is None:
            continue
        (result,) = step.content.blocks
        assert isinstance(result, ToolResultBlock)
        if result.tool_use_id != use_id:
            continue
        head = result.parts[0]
        assert isinstance(head, TextBlock)
        pages: list[str] = []
        while True:
            page = await platform.managers.windows.get_tool_output(
                platform.owner, agent_session_id, header.artifact.id, len("".join(pages)), 100_000
            )
            pages.append(page.text)
            if not page.has_more:
                return head.text, "".join(pages)
    raise AssertionError(f"no answer to {use_id} kept as an artifact")


async def test_a_pull_request_too_large_for_one_answer_keeps_its_id_and_head_whole(
    tmp_path: Path,
) -> None:
    """A mass rename of 1,500 files, its body past what one answer holds:
    the read lists the files that fit, counts the rest, and cuts nothing
    else, so its id and its head are whole for the review to cite."""
    renamed = tuple(
        ChangedFile(
            path=f"src/generated/client_{n:04d}.py",
            status="renamed",
            patch="@@ -1 +1 @@\n-old\n+new",
        )
        for n in range(1500)
    )
    forge = IntegrationTwinImpl(FORGE)
    forge.record_pull_request(
        RECORDED.model_copy(update={"files": renamed, "body": "x" * 60_000}), {}
    )
    platform = platform_over(tmp_path, forge=forge)
    await platform.connect(FORGE, twin_installation("acme"))
    agent_session_id = await platform.start(kinds.REVIEWER)
    await platform.say(agent_session_id, f"Review {REVIEWED}.")
    platform.anthropic.add(
        reply(calls(kinds.READ_PULL_REQUEST, "use_read", on=REVIEWED)),
        reply(said("It renames 1,500 files.")),
    )

    await platform.managers.loop.run(platform.owner, agent_session_id)

    failure, _ = await platform.answer(agent_session_id, "use_read")
    shown, whole = await kept_whole(platform, agent_session_id, "use_read")
    assert failure is None and len(whole) <= MAX_VIEW
    read = json.loads(whole)
    assert UUID(read["id"]) in {step.id for step in await platform.history(agent_session_id)}
    assert read["head"] == REVIEWED_HEAD
    listed = len(read["files"])
    assert 0 < listed < len(renamed)
    assert read["files_left_out"] == len(renamed) - listed and read["complete"] is False
    assert [f["path"] for f in read["files"]] == [f.path for f in renamed[:listed]]
    assert read["patches_left_out"] == sum(f["patch"] is None for f in read["files"])
    assert len(read["body"]) < 11_000 and "[cut:" in read["body"]
    # What the window shows at once holds the id, the head, and the count.
    for field in ("id", "head", "files_left_out"):
        assert f'"{field}":{json.dumps(read[field])}' in shown, field
