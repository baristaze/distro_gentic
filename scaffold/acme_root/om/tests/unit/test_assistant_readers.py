"""The platform assistant's readers, over memory: its registry holds them
and the tools a product's slot names, and a slot that names a tool it may
not call is refused at start; a reader refuses an input it does not
declare before it reads anything; a list of sessions filters by park
reason and project and says where to read on; read_wait names the offline
host that holds a session's workspace; and the object model names every
park reason the engine has and every unlock it writes, each with its
cause, who may clear it, and the reader that shows it."""

import ast
import json
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.hosts_storage import make_credential, make_host
from contracts.loops import reply, said
from contracts.platform_agents import CORPUS, Platform, calls, platform_over
from contracts.project_storage import in_project

from acme.infra.impl.local import InfraLocalImpl
from acme.om.agents.types.kind import NO_WORKSPACE, AgentKind, DoneRule, TreeLimits
from acme.om.agents.types.request import Start
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import Platform as Record
from acme.om.base import new_id, utcnow
from acme.om.context import TenantContext
from acme.om.exceptions import UnsafeConfiguration
from acme.om.hosts.impl.manager import HostsOptions
from acme.om.hosts.types.pool import HostPool
from acme.om.platform_agents import kinds
from acme.om.platform_agents.catalog import PlatformAgents, read_corpus, with_assistant_tools
from acme.om.platform_agents.kinds import (
    ASSISTANT_READERS,
    PLATFORM_ASSISTANT_KIND,
    PLATFORM_ASSISTANT_V1,
    SHIPPED,
)
from acme.om.platform_agents.tools import NativeToolImpl
from acme.om.root import Managers, ProductKinds, build_managers
from acme.om.steps.types.header import LoopOutcome, ParkReason, ToolFailure
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tools.tool import ToolInterface, ToolRuntime
from acme.om.tools.types.policy import PolicyLayer
from acme.om.tools.types.tool import Effect, ToolClass, ToolInput, ToolMode, ToolSpec

ROOT = Path(__file__).resolve().parents[3]
OBJECT_MODEL = ROOT / "docs" / "object-model.md"
ENGINE = ROOT / "om/src/acme/om"


class Nothing(ToolInput):
    pass


class Tally(Record):
    count: int


def a_reader(name: str, authorization_class: str = ToolClass.READ) -> type[NativeToolImpl]:
    """A product's tool of `authorization_class` that reads nothing."""

    class ReaderImpl(NativeToolImpl):
        SPEC = ToolSpec(
            name=name,
            description="Counts what the product holds.",
            input_model=Nothing,
            output_model=Tally,
            timeout=timedelta(seconds=10),
            authorization_class=authorization_class,
            effect=Effect.READ_ONLY,
            interruptible=True,
            mode=ToolMode.SYNC,
        )

        async def run(
            self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
        ) -> Record:
            return Tally(count=3)

    return ReaderImpl


def tools_of(
    *tools: type[NativeToolImpl],
) -> Callable[[Callable[[], Managers]], tuple[ToolInterface, ...]]:
    def build(managers: Callable[[], Managers]) -> tuple[ToolInterface, ...]:
        return tuple(tool() for tool in tools)

    return build


# Check: the assistant's registry holds the readers, and a product's named
# tool joins it; a name no tool has is refused at start.


async def test_the_assistants_registry_holds_its_readers_and_the_tool_a_product_names(
    tmp_path: Path,
) -> None:
    product = ProductKinds(tools=tools_of(a_reader("read_tally")), assistant_tools=("read_tally",))
    platform = platform_over(tmp_path, product_kinds=product)

    session_id = await platform.start(kinds.PLATFORM_ASSISTANT)

    session = await platform.managers.agent_sessions.get_session(platform.owner, session_id)
    assert session.kind_version == PLATFORM_ASSISTANT_KIND.version == 2
    readers = {*ASSISTANT_READERS, kinds.SEARCH_KNOWLEDGE, kinds.READ_KNOWLEDGE}
    assert readers <= set(session.tools)
    assert "read_tally" in session.tools
    # The product's tool joins the current version alone: a session still on
    # the version before keeps what it named.
    joined = with_assistant_tools(SHIPPED, ("read_tally",))
    assert PLATFORM_ASSISTANT_V1 in joined
    assert "read_tally" not in PLATFORM_ASSISTANT_V1.tools
    # A kind of the product's own never gains it.
    engineer_id = await platform.start(kinds.ENGINEER)
    engineer = await platform.managers.agent_sessions.get_session(platform.owner, engineer_id)
    assert "read_tally" not in engineer.tools


@pytest.mark.parametrize(
    ("product", "refused"),
    [
        # A name no tool of the catalog has.
        (ProductKinds(assistant_tools=("read_nothing",)), "read_nothing"),
        # A tool past what the assistant may call.
        (
            ProductKinds(
                tools=tools_of(a_reader("write_tally", ToolClass.WRITE)),
                assistant_tools=("write_tally",),
            ),
            "write_tally",
        ),
        # A name the assistant holds already, or one named twice.
        (ProductKinds(assistant_tools=(kinds.READ_SESSION,)), kinds.READ_SESSION),
        (
            ProductKinds(
                tools=tools_of(a_reader("read_tally")),
                assistant_tools=("read_tally", "read_tally"),
            ),
            "twice",
        ),
    ],
)
def test_a_slot_that_names_a_tool_the_assistant_may_not_call_is_refused_at_start(
    tmp_path: Path, product: ProductKinds, refused: str
) -> None:
    with pytest.raises(UnsafeConfiguration, match=refused):
        build_managers(
            StorageMemoryImpl(),
            InfraLocalImpl(tmp_path),
            platform_agents=PlatformAgents(corpus=CORPUS),
            product_kinds=product,
        )


# Check: a reader's input from the model is refused when it is malformed,
# before anything is read.


async def test_a_readers_malformed_input_is_refused_never_a_crash(tmp_path: Path) -> None:
    platform = platform_over(tmp_path)
    session_id = await platform.start(kinds.PLATFORM_ASSISTANT)
    await platform.say(session_id, "What is stuck?")
    malformed = {
        "bad_id": calls(kinds.READ_SESSION, "bad_id", session_id="not-a-session"),
        "no_id": calls(kinds.READ_WAIT, "no_id"),
        "extra": calls(kinds.READ_PROJECT, "extra", project_id=str(new_id()), org_id="x"),
        "zero": calls(kinds.LIST_SESSIONS, "zero", limit=0),
        "huge": calls(kinds.LIST_PROJECTS, "huge", limit=10_000),
        "status": calls(kinds.LIST_SESSIONS, "status", status="stuck"),
        "reason": calls(kinds.LIST_SESSIONS, "reason", park_reason="person", status="idle"),
        "cursor": calls(kinds.LIST_AUTOMATIONS, "cursor", after="page-2"),
        "runs": calls(kinds.READ_AUTOMATION, "runs", automation_id=str(new_id()), runs=500),
    }
    platform.anthropic.add(
        reply(said("Let me read."), *malformed.values()),
        reply(said("I could not read that.")),
    )

    run = await platform.managers.loop.run(platform.owner, session_id)

    # The streak of refusals may end the loop, as the engine ends any; none
    # of them is an error.
    assert run.outcome is not LoopOutcome.ERRORED
    for use_id in malformed:
        failure, _ = await platform.answer(session_id, use_id)
        assert failure is ToolFailure.INVALID_INPUT, use_id


# A list of sessions filters by park reason and by project.

CLERK = AgentKind(
    name="clerk",
    version=1,
    tools=(kinds.SEARCH_CORPUS,),
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.STEADY,
    tree=TreeLimits(height=1, count=0),
    prompts=("Look it up.",),
    policy=PolicyLayer(),  # it allows nothing, so its every call waits for a person
    isolation=NO_WORKSPACE,
)


async def held_session(platform: Platform) -> UUID:
    """A clerk's session parked on the call it holds for approval."""
    start = Start(id=new_id(), kind=CLERK.name, title="a held lookup")
    session = await platform.managers.agents.start_session(platform.owner, start)
    await platform.say(session.id, "Look up why sessions wait.")
    platform.anthropic.add(reply(calls(kinds.SEARCH_CORPUS, "use_lookup", query="wait")))
    await platform.managers.loop.run(platform.owner, session.id)
    held = await platform.managers.agent_sessions.get_session(platform.owner, session.id)
    assert held.park is not None and held.park.reason is ParkReason.PERSON
    return session.id


async def test_a_list_of_sessions_filters_by_park_reason_and_project_and_reads_on(
    tmp_path: Path,
) -> None:
    platform = platform_over(tmp_path, kinds=(CLERK,))
    first = await held_session(platform)
    second = await held_session(platform)
    idle = await platform.start(kinds.ENGINEER)
    projects = platform.storage.get_project_storage()
    project_id = await in_project(projects, platform.owner.org_id, first, idle)
    asking = await platform.start(kinds.PLATFORM_ASSISTANT)
    await platform.say(asking, "Which sessions wait for a person?")
    platform.anthropic.add(
        reply(
            calls(kinds.LIST_SESSIONS, "use_person", park_reason="person", limit=1),
            calls(kinds.LIST_SESSIONS, "use_idle", status="idle"),
            calls(
                kinds.LIST_SESSIONS, "use_project", park_reason="person", project_id=str(project_id)
            ),
        ),
        reply(said("Two wait for a person.")),
    )

    await platform.managers.loop.run(platform.owner, asking)

    failure, text = await platform.answer(asking, "use_person")
    page = json.loads(text)
    assert failure is None
    # Newest first, one at a time, with where to read on.
    assert [s["session_id"] for s in page["sessions"]] == [str(second)]
    assert page["sessions"][0]["park_reason"] == "person"
    assert page["next"] == str(second)
    platform.anthropic.add(
        reply(calls(kinds.LIST_SESSIONS, "use_on", park_reason="person", before=page["next"])),
        reply(said("And one more.")),
    )
    await platform.say(asking, "And the rest?")
    await platform.managers.loop.run(platform.owner, asking)
    _, text = await platform.answer(asking, "use_on")
    rest = json.loads(text)
    assert [s["session_id"] for s in rest["sessions"]] == [str(first)]
    assert rest["next"] is None
    _, text = await platform.answer(asking, "use_idle")
    listed = {s["session_id"] for s in json.loads(text)["sessions"]}
    assert str(idle) in listed and str(first) not in listed
    # Of the two that wait, only the first is in the project.
    _, text = await platform.answer(asking, "use_project")
    in_it = json.loads(text)
    assert [s["session_id"] for s in in_it["sessions"]] == [str(first)]
    assert in_it["next"] is None


# Check: read_wait on a session pinned to an offline host names that host
# and that it is offline, beside the pool's other hosts.


async def a_host(platform: Platform, pool_id: UUID, name: str, last_seen_at: datetime) -> UUID:
    """A host of the pool, enrolled at its storage, last seen at `last_seen_at`."""
    host = make_host(pool_id).model_copy(update={"name": name, "last_seen_at": last_seen_at})
    hosts = platform.storage.get_hosts_storage()
    await hosts.enroll(platform.owner.org_id, host, make_credential(host.id), ())
    return host.id


async def test_a_wait_on_the_offline_host_that_holds_the_workspace_names_that_host(
    tmp_path: Path,
) -> None:
    platform = platform_over(tmp_path)
    hosts = platform.managers.hosts
    now = utcnow()
    pool = await hosts.create_pool(
        platform.owner,
        HostPool(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=platform.owner.user_id,
            updated_by=platform.owner.user_id,
            name="build",
            region="eu-west",
        ),
    )
    # The host that prepared the workspace is silent; the other calls in.
    silent_since = now - 2 * HostsOptions().online_window
    holder = await a_host(platform, pool.id, "host-1", silent_since)
    await a_host(platform, pool.id, "host-2", now)
    pinned = await platform.start(kinds.ENGINEER)
    await hosts.place_session(platform.owner, pinned, pool.id)
    await platform.managers.relay.bind_workspace(platform.owner, pinned, holder, "/srv/work")
    asking = await platform.start(kinds.PLATFORM_ASSISTANT)
    await platform.say(asking, "Why has my session not started?")
    platform.anthropic.add(
        reply(calls(kinds.READ_WAIT, "use_wait", session_id=str(pinned))),
        reply(said("It waits for host-1, which is offline.")),
    )

    await platform.managers.loop.run(platform.owner, asking)

    failure, text = await platform.answer(asking, "use_wait")
    wait = json.loads(text)
    assert failure is None
    # Another host of its pool is online, and the session still waits: for
    # the one that holds its workspace, offline since it was last seen.
    assert wait["hosts_online"] == 1
    assert {h["name"]: h["online"] for h in wait["hosts"]} == {"host-1": False, "host-2": True}
    assert wait["workspace_host"]["name"] == "host-1"
    assert wait["workspace_host"]["online"] is False
    assert datetime.fromisoformat(wait["workspace_host"]["last_seen_at"]) == silent_since
    assert wait["waits_for_a_host"] is True


# Check: docs/object-model.md names every park reason and every unlock the
# engine writes, each with its cause and who may clear it.

COMPUTED = {
    "agents/impl/loop.py: fill.provider.value": "a provider's name",
    "agents/impl/loop.py: refused.unlock": "`<provider>:key`",
    "agents/impl/loop.py: unlock": "`<provider>:billing`",
    "agents/impl/loop.py: str(started.key)": "a job's key",
    "budgets/rules.py: unlock": "a budget's id",
}
"""Each unlock the engine computes rather than names, by the module and the
expression that compute it, with the start of its row in the object model."""


def section(document: str, heading: str) -> str:
    return document.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]


def named_in(table: str) -> set[str]:
    """What the first column of a table names in code font."""
    return {
        match.group(1)
        for line in table.splitlines()
        if (match := re.match(r"^\| `([a-z_]+)` \|", line)) is not None
    }


def park_reasons_in(document: str) -> set[str]:
    return named_in(section(document, "Why a session is parked"))


def unlocks_in_code() -> tuple[set[str], set[str]]:
    """What the engine parks on: each unlock it names, as a module's
    `*_UNLOCK` constant or a literal a `Park` is given, and each one it
    computes, as the module and the expression that compute it."""
    named: set[str] = set()
    computed: set[str] = set()
    for path in sorted(ENGINE.rglob("*.py")):
        module = path.relative_to(ENGINE).as_posix()
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(target := node.targets[0], ast.Name)
                and target.id.endswith("_UNLOCK")
                and isinstance(node.value, ast.Constant)
            ):
                named.add(str(node.value.value))
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Park"
            ):
                for keyword in node.keywords:
                    if keyword.arg != "unlock":
                        continue
                    if isinstance(keyword.value, ast.Constant):
                        named.add(str(keyword.value.value))
                    elif not ast.unparse(keyword.value).endswith("_UNLOCK"):
                        computed.add(f"{module}: {ast.unparse(keyword.value)}")
    return named, computed


def test_the_object_model_names_every_park_reason_the_engine_has() -> None:
    document = OBJECT_MODEL.read_text()
    assert park_reasons_in(document) == {reason.value for reason in ParkReason}
    # Each reader the assistant holds is named where it shows a thing.
    for reader in ASSISTANT_READERS:
        assert f"`{reader}`" in document, reader
    # And the assistant answers from it: the map lists it for the tenant's
    # users.
    assert "docs/object-model.md" in [d.path for d in read_corpus(ROOT).documents]


def test_a_park_table_that_drops_a_reason_fails_the_check() -> None:
    document = OBJECT_MODEL.read_text()
    dropped = document.replace("| `handover` |", "| handover |")
    assert ParkReason.HANDOVER.value not in park_reasons_in(dropped)


def test_the_object_model_names_every_unlock_the_engine_writes() -> None:
    named, computed = unlocks_in_code()
    table = section(OBJECT_MODEL.read_text(), "What each park waits on")
    assert named_in(table) == named
    assert computed == set(COMPUTED)
    for start in COMPUTED.values():
        assert f"\n| {start}" in table, start
    # Each row says its reason, its cause, what clears it, who may clear
    # it, and the reader that shows it.
    rows = [line for line in table.splitlines() if line.startswith("| ")][2:]
    reasons = {f"`{reason.value}`" for reason in ParkReason}
    for row in rows:
        cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
        assert len(cells) == 6 and all(cells), row
        assert cells[1] in reasons, row
        assert "`read_" in cells[5], row


def test_an_unlock_table_that_drops_an_unlock_fails_the_check() -> None:
    table = section(OBJECT_MODEL.read_text(), "What each park waits on")
    named, _ = unlocks_in_code()
    assert "principal" in named
    assert named_in(table.replace("| `principal` |", "| principal |")) != named
