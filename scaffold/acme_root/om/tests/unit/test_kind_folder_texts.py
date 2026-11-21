"""A kind's own manuals and wiki reach its sessions as the kind's own. Its
manuals open each new session's standing text, before the kind manual its
tenant pinned, and render whole in the system layer of every request; a
pin that would not fit after them is refused. Its wiki entries are
recalled as its sessions start, as data, and found and read by their
handle, `<kind>/<slug>`, under the scope `kind`. None of them is a
tenant's: no tenant's row holds them, no recall of them is kept, a session
of another kind never reaches them, and a tenant's entry is never read as
one."""

import json
from pathlib import Path
from types import ModuleType
from uuid import UUID

import pytest

from acme.om.agent_knowledge.types.agent_knowledge import (
    AgentKnowledge,
    AgentKnowledgeStatus,
    KindEntry,
)
from acme.om.agent_playbooks.rules import skill_md
from acme.om.agent_playbooks.types.agent_playbook import AgentPlaybookDraft
from acme.om.agent_steps.rules import message_step
from acme.om.agent_steps.types.agent_step import AgentStepType
from acme.om.agents.prompts import LOCK, PROMPTS, digest
from acme.om.agents.types.request import MAX_STANDING, Start
from acme.om.agents.types.run import RunEnd
from acme.om.base import new_id, utcnow
from acme.om.exceptions import ValidationFailed
from acme.om.platform_agents.folders import MANUALS, WIKI, KindFolder, folder_breaches, folder_of
from acme.om.windows.rules import STANDING_LEAD

from contracts.agent_knowledge_tools import Asking
from contracts.intake import Wired, wired
from contracts.loops import reply, said
from contracts.trust import STEADY

LEDGER = STEADY.model_copy(update={"name": "ledger"})
"""A product's kind, kept as a folder of its own."""

CLOSE = "Close the month on its last business day, after the bank feed lands."
TOTALS = "Quote the ledger's line for each total you give."
MONTH_END = "The bank feed lands by six in the morning on the month's last business day."
TENANTS = "Our month closes a day late in December."


def ledger(tmp_path: Path) -> KindFolder:
    """The ledger's folder, as a product keeps it: its prompt pinned in its
    lock, two manuals, whose files sort apart from the order they were
    written in, and one wiki entry. The checks find nothing in it."""
    folder = tmp_path / "kinds" / "ledger"
    (folder / PROMPTS).mkdir(parents=True)
    (prompt,) = LEDGER.prompts
    (folder / PROMPTS / "v1.md").write_text(prompt + "\n", encoding="utf-8")
    (folder / PROMPTS / LOCK).write_text(json.dumps({"v1.md": digest(prompt)}), encoding="utf-8")
    (folder / MANUALS).mkdir()
    (folder / WIKI).mkdir()
    (folder / MANUALS / "totals.md").write_text(TOTALS + "\n", encoding="utf-8")
    (folder / MANUALS / "month-close.md").write_text(CLOSE + "\n", encoding="utf-8")
    (folder / WIKI / "month-end.md").write_text(
        f"---\ntitle: When the month ends\ntrigger: month, close\n---\n\n{MONTH_END}\n",
        encoding="utf-8",
    )
    module = ModuleType("ledger")
    module.__file__ = str(folder / "kind.py")
    module.VERSIONS = (LEDGER,)  # pyright: ignore[reportAttributeAccessIssue]
    assert folder_breaches(folder, (LEDGER,), (LEDGER.name, STEADY.name)) == ()
    return folder_of(module)


@pytest.fixture
def platform(tmp_path: Path) -> Wired:
    return wired(tmp_path / "platform", folders=(ledger(tmp_path),))


async def a_ledger(platform: Wired, title: str = "the month close") -> UUID:
    session = await platform.managers.agents.start_agent_session(
        platform.owner, Start(id=new_id(), kind=LEDGER.name, title=title)
    )
    return session.id


# Check 2: a kind's manuals and wiki entries reach its sessions as the
# kind's own, and no tenant's.


async def test_a_kinds_manuals_open_its_sessions_standing_text_before_its_tenants_kind_manual(
    platform: Wired,
) -> None:
    pinned = await platform.agent_playbooks.publish(
        platform.owner,
        AgentPlaybookDraft(
            name="ledger-kind-manual",
            description="How the team answers from the ledger.",
            body="Name the account of every line you quote.",
        ),
    )
    await platform.agent_playbooks.pin(platform.owner, LEDGER.name, pinned.name)
    ours = await platform.managers.agents.start_agent_session(
        platform.owner, Start(id=new_id(), kind=LEDGER.name, title="the month close")
    )
    message = message_step(new_id(), utcnow(), ours.id, platform.owner, "Close the month.")
    await platform.managers.agent_sessions.receive(platform.owner, ours.id, [message])
    platform.anthropic.add(reply(said("Closed.")))
    assert (await platform.loops.run(platform.owner, ours.id)).end is RunEnd.ENDED
    system = [block.text for block in platform.anthropic.calls[-1].system]
    own = f"{CLOSE}\n\n{TOTALS}"
    assert system[1] == f"{STANDING_LEAD}\n\n{own}\n\n{skill_md(pinned)}"
    # Another kind's session holds none of them, and the tenant holds no row
    # of them: its one agent playbook is its own.
    other = await platform.start()
    message = message_step(new_id(), utcnow(), other, platform.owner, "Read the records.")
    await platform.managers.agent_sessions.receive(platform.owner, other, [message])
    platform.anthropic.add(reply(said("Read.")))
    assert (await platform.loops.run(platform.owner, other)).end is RunEnd.ENDED
    rendered = platform.anthropic.calls[-1].model_dump_json()
    assert CLOSE not in rendered and TOTALS not in rendered
    assert [pin.name for pin in await platform.agent_playbooks.pins(platform.owner)] == [
        pinned.name
    ]


async def test_a_pin_that_fits_alone_but_not_after_the_kinds_manuals_is_refused(
    platform: Wired,
) -> None:
    empty = AgentPlaybookDraft(name="long-manual", description="Long.", body="x")
    frame = len(skill_md(await platform.agent_playbooks.publish(platform.owner, empty))) - 1
    own = len(f"{CLOSE}\n\n{TOTALS}") + 2
    body = "x" * (MAX_STANDING - frame - own + 1)
    await platform.agent_playbooks.publish(platform.owner, empty.model_copy(update={"body": body}))
    await platform.agent_playbooks.pin(platform.owner, "steady", "long-manual")
    with pytest.raises(ValidationFailed, match="after the ledger kind's own manuals"):
        await platform.agent_playbooks.pin(platform.owner, LEDGER.name, "long-manual")
    assert [pin.kind for pin in await platform.agent_playbooks.pins(platform.owner)] == ["steady"]


async def test_a_kinds_wiki_reaches_its_sessions_as_the_kinds_own_and_no_tenants(
    platform: Wired, tmp_path: Path
) -> None:
    asking = Asking(platform, tmp_path)
    tenants = await platform.agent_knowledge.write(
        platform.owner, "Our month close", ("month", "close"), TENANTS
    )
    ours = await a_ledger(platform)
    theirs = await platform.start()
    agent = await platform.agents_call(platform.owner)
    # Recall: the kind's own first, then the tenant's, each as data; only the
    # tenant's recall is kept, since the kind's is no tenant's lever.
    session = await platform.managers.agent_sessions.get_agent_session(platform.owner, ours)
    recalled = await platform.agent_knowledge.recall(platform.service, session.id, "month close")
    assert [type(entry) for entry in recalled] == [KindEntry, AgentKnowledge]
    events = [
        step.as_text()
        for step in await platform.history(session.id)
        if step.type is AgentStepType.EVENT
    ]
    assert events == [
        f"agent knowledge, your kind's own: When the month ends\n{MONTH_END}",
        f"agent knowledge: Our month close\n{TENANTS}",
    ]
    kept = await platform.storage.get_agent_knowledge_storage().read_recalls(
        platform.owner.org_id, session.id, 10
    )
    assert [recall.entry_id for recall in kept] == [tenants.id]
    # Search and read: the kind's own under its scope and its handle.
    assert await asking.found(agent, session.id, "month close") == {
        "kind:When the month ends",
        "tenant:Our month close",
    }
    assert await asking.text_of(agent, session.id, "ledger/month-end") == MONTH_END
    # Another kind's session neither finds it nor reads it.
    other = await platform.managers.agent_sessions.get_agent_session(platform.owner, theirs)
    assert await asking.found(agent, other.id, "month close") == {"tenant:Our month close"}
    assert await asking.text_of(agent, other.id, "ledger/month-end") is None
    assert [
        type(entry)
        for entry in await platform.agent_knowledge.recall(
            platform.service, other.id, "month close"
        )
    ] == [AgentKnowledge]
    # The tenant's own rows are its entry alone.
    assert [
        entry.id
        for entry in await platform.agent_knowledge.list_entries(
            platform.owner, AgentKnowledgeStatus.REVIEWED, None, 50
        )
    ] == [tenants.id]


async def test_a_session_of_the_kind_reads_its_kinds_entry_at_its_first_call(
    platform: Wired,
) -> None:
    ours = await a_ledger(platform, title="the month close")
    session = await platform.managers.agent_sessions.get_agent_session(platform.owner, ours)
    message = message_step(new_id(), utcnow(), session.id, platform.owner, "Close the month.")
    await platform.managers.agent_sessions.receive(platform.owner, session.id, [message])
    platform.anthropic.add(reply(said("Closed.")))
    assert (await platform.loops.run(platform.owner, session.id)).end is RunEnd.ENDED
    first = platform.anthropic.calls[-1].model_dump_json()
    assert first.count('<data origin=\\"event\\"') == 1
    assert "your kind's own: When the month ends" in first
