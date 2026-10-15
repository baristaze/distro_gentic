"""The platform's fresh executor, over its own workspaces. Each run gets an
instance nobody used before, made for that run alone under an id of its
own, and destroyed when the run ends, whatever ended it: nothing of one run
is there for the next.

The tree comes in from outside: the delivered commit with the checks,
fixtures, and runner taken from the protected source, read from the
agent project's repository by the platform (`Tree`) and written in as files. A
hidden suite's source is a repository of its own, which the request
names by its agent project. No
credential and no history enters the instance, and nothing leaves it: its
egress is none. Every file of the tree the request protects, or keeps
untouched, is read-only before a check runs, and a trial after which one
is not as the executor left it ran to no verdict: its inode, its mode, its
size, and the time its inode last changed, which no process of the
instance sets back, are read before the first trial and after each. A
folder stays writable: a check, or the head's code, may add a new file in
a protected folder, and no file the tree held there changes unseen. The
digest holds against code that leaves the instance's `stat` and
`sha256sum` as they are; code that puts its own first on the path fakes
it, and only a check run as a user apart from the tree's owner stops
that. Each check's
command template runs with `{version}` and `{out}` filled, in the tree,
under the environment of the instance's image and its transport, never one
an agent set. Each trial's results stream is read back within the bound,
and within what one read of its transport carries, and the executor hashes
what it read. Every trial counts: one that ran past its time, or wrote no
stream the collector reads as one run of its check at the version asked,
is written as an `errored` run by the executor itself, so asking again
until a run passes hides no failure. A run's record names the host,
isolation, and image the executor made, never what the delivered code's
start line says.

For a session of the cloud, the instance is the cloud's, made by the
provider and reached by the transport the platform's own processes hold. A
session inside its tenant's wall never runs on them: its instance is made
by a host of its pool, to the isolation the session is pinned to, which
its pool gives it, and reached through the relay
(`PlacedInstancesInterface`). A root that wires no such way refuses its
checks, loudly.

A session pinned to a base, such as its agent project's workspace base, has its
checks run on that base, so what its setup installed is there for them:
the base's image and the snapshot its setup left, never the session's
workspace or a snapshot of it. The instance's egress is none even so: the
setup's egress is the build's alone. In the cloud, the base is the
tenant's, read where it is kept or built once (`Bases`); inside the wall,
the host that makes the instance builds it or reads it from its own
store. A base with setup and no way to read it refuses the checks before
anything runs, never runs them on the bare image."""

import io
import json
import logging
import tarfile
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import NamedTuple
from uuid import UUID

from pydantic import Field

from acme.infra.agent_workspaces import (
    AgentWorkspaceProviderInterface,
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationSpec,
    ResourceLimits,
    AgentWorkspace,
)
from acme.infra.exceptions import InfraException
from acme.infra.transports import CommandResult, CommandSpec, RecordSeal, TransportInterface
from acme.om.agent_workspaces.placed import PlacedInstancesInterface
from acme.om.base import OmBase, new_id, utcnow
from acme.om.context import TenantContext
from acme.om.evidence.collector import collect, digest
from acme.om.evidence.executor import ExecutorInterface
from acme.om.evidence.rates import stops_at
from acme.om.evidence.rules import protected_paths
from acme.om.evidence.types.contract import SCHEMAS, CheckDeclaration, Offer
from acme.om.evidence.types.record import VERSION, ExecutionRecord, RunOutcome
from acme.om.evidence.types.validation import ExecutionRequest, ExecutorReport, Prepared
from acme.om.exceptions import Unavailable, ValidationFailed

log = logging.getLogger(__name__)

ARCHIVE = "tree.tar"
"""Where the tree's tar is written in the instance, until it is unpacked."""
TREE = "tree"
"""Where the tree is unpacked, under the instance's root: the checks run here."""
OUT = "out"
"""Where each trial's results stream goes, beside the tree, never in it."""
UNPACK = 'mkdir -p "$1" "$2" && tar -xf "$3" -C "$1" && rm -f "$3" && pwd'
"""Unpacks the tree and answers the instance's root, as its commands see it."""
LOCK = 'chmod -- a-w "$@"'
"""Makes each file of the tree a run protects read-only, and never a
folder: no process of the check writes the file without changing its mode,
and a new file beside it is the check's to write."""
SEEN = (
    "seen=$(if stat -c %i . >/dev/null 2>&1;"
    ' then stat -c "%n %i %a %s %z" -- "$@";'
    ' else stat -f "%N %i %Lp %z %Fc" -- "$@"; fi)'
    " && if command -v sha256sum >/dev/null;"
    ' then printf "%s\\n" "$seen" | sha256sum;'
    ' else printf "%s\\n" "$seen" | shasum -a 256; fi'
)
"""One digest of what the instance holds at each file and link a run
protects: its inode, mode, size, and the time its inode last changed, to the nanosecond,
by GNU's `stat` and `sha256sum`, or by BSD's `stat` and `shasum` on a host
that has those. A write, a change of mode, or a replacement moves that
time, and no process of the instance sets it back. A path gone fails it."""
EPOCH = 1
"""The one epoch of an instance's commands: no other run ever reaches it."""
Tree = Callable[
    [TenantContext, UUID, str, str, tuple[str, ...], UUID, str | None, tuple[str, ...]],
    Awaitable[bytes],
]
"""The tree a validation of an agent project runs on, as a tar, by the agent project, the
commit, the protected source, the protected patterns, the agent project whose
repository holds the source, and the base and patterns of the paths no
change may touch: the workspaces' (`AgentWorkspacesManagerInterface.checks_tree`)."""
MISSING = 404
"""The status a transport answers for a file the instance does not hold."""
TOO_LARGE = 413
"""The status a transport answers for a file longer than one read of it
carries, with that bound in its message."""
SPOKEN = 10_000
"""The most of a command's own output kept: a check writes its results to
`{out}`, never to its output."""


class Pin(NamedTuple):
    """A session's pin, as its checks read it: the isolation it is pinned
    to, its base included, and whether it runs inside its tenant's wall."""

    spec: IsolationSpec
    walled: bool


Pinned = Callable[[TenantContext, UUID], Awaitable[Pin | None]]
"""The pin of a session; None for a session of the cloud that pinned no
isolation, whose checks run as the executor's own."""
Bases = Callable[[TenantContext, IsolationSpec], Awaitable[bytes]]
"""The snapshot of the base a spec names, as its provider starts a
workspace from it: read where the tenant keeps it, or built once
(`AgentWorkspaceBases.archive`)."""
PLACED = "pool"
"""What a record names as the host and the image of an instance a host of
a pinned session's pool made: the pool's, which the executor does not
choose. On a base, the image is the base's, which the executor asked for."""


class ExecutorOptions(OmBase):
    # The isolation each instance of the cloud's is made at: a container
    # with no egress, as the cloud's executors are. One on a host of a pinned
    # session's pool is made to the session's own isolation instead.
    isolation: IsolationMode = IsolationMode.CONTAINER
    limits: ResourceLimits = ResourceLimits()
    # What the instance's image offers a check, as its declaration names it.
    capabilities: frozenset[str] = frozenset()
    # How long the tree's unpacking may take, and one trial of a check.
    setup_time: timedelta = timedelta(minutes=5)
    trial_time: timedelta = timedelta(minutes=20)
    # The most of a run's results streams read back, all trials together.
    max_results_bytes: int = Field(default=64 * 1024 * 1024, gt=0)
    # What a record names of the cloud's instances, never what a runner's
    # start line says: the host that makes them, and the image they run
    # when the session's pin names no base.
    host: str = Field(default="cloud", min_length=1, max_length=200)
    image: str = Field(default="python:3.14", pattern=VERSION)


async def _kept_nowhere(data: bytes) -> bytes | None:
    """An instance's commands keep no output at rest: it goes with the
    instance."""
    return None


SEAL = RecordSeal(seal=_kept_nowhere, open=_kept_nowhere)


class ExecutorAgentWorkspacesImpl(ExecutorInterface):
    def __init__(
        self,
        provider: AgentWorkspaceProviderInterface,
        transport: TransportInterface,
        tree: Tree,
        pinned: Pinned,
        placed: PlacedInstancesInterface | None = None,
        options: ExecutorOptions | None = None,
        clock: Callable[[], datetime] = utcnow,
        *,
        bases: Bases | None = None,
    ) -> None:
        self._provider = provider
        self._transport = transport
        self._tree = tree
        self._pinned = pinned
        self._placed = placed
        self._options = options or ExecutorOptions()
        self._clock = clock
        self._bases = bases

    async def offer(self, ctx: TenantContext) -> Offer:
        return Offer(capabilities=self._options.capabilities, schemas=SCHEMAS)

    async def run(self, ctx: TenantContext, request: ExecutionRequest) -> ExecutorReport:
        pin = await self._pinned(ctx, request.agent_session_id)
        walled = pin is not None and pin.walled
        if walled and self._placed is None:
            raise Unavailable(
                f"session {request.agent_session_id} runs inside its tenant's wall, and this "
                "process reaches no host of its pool, so its checks never run here"
            )
        base = None if pin is None else pin.spec.base
        # Inside the wall, the host that makes the instance reads its base.
        built = not walled and base is not None and bool(base.setup)
        if built and self._bases is None:
            raise Unavailable(
                f"session {request.agent_session_id} is pinned to a base with setup, and this "
                "process reads no base, so its checks never run on the bare image"
            )
        named = (request.agent_project, request.source_agent_project or request.agent_project)
        try:
            agent_project_id, source_id = (UUID(agent_project) for agent_project in named)
        except ValueError:
            raise Unavailable(
                f"no agent project's id to validate in {sorted(set(named))}"
            ) from None
        tree = await self._tree(
            ctx,
            agent_project_id,
            request.version,
            request.source,
            request.protected,
            source_id,
            request.base,
            request.untouched,
        )
        instance = new_id()
        if pin is None or not walled:
            spec = IsolationSpec(
                mode=self._options.isolation,
                egress=EgressPolicy(mode=EgressMode.NONE),
                limits=self._options.limits,
                base=base,
            )
            # The tenant's base holds what its setup left, and nothing of the
            # session's: its workspace and its snapshots stay apart.
            archive = None
            if built:
                assert self._bases is not None  # refused above
                archive = await self._bases(ctx, spec)
            try:
                workspace = await self._provider.prepare(ctx.org_id, instance, spec, base=archive)
                prepared = Prepared(
                    host=self._options.host,
                    isolation=workspace.spec.mode.value,
                    image=self._options.image if base is None else base.image,
                )
                results = await self._checks(self._transport, workspace, request, tree, prepared)
            finally:
                await self._provider.purge(ctx.org_id, instance)
                await self._transport.purge_records(instance)
        else:
            assert self._placed is not None  # refused above
            # On a base, the instance asks no egress, as the cloud's does, so
            # neither the setup's nor the session's reaches the checks. With
            # none, it is the session's isolation whole, which even a pool of
            # bare directories gives.
            spec = pin.spec
            if base is not None:
                spec = spec.model_copy(update={"egress": EgressPolicy(mode=EgressMode.NONE)})
            try:
                workspace, transport = await self._placed.make(
                    ctx,
                    request.agent_session_id,
                    instance,
                    spec,
                    self._clock() + self._options.setup_time,
                )
                prepared = Prepared(
                    host=PLACED,
                    isolation=workspace.spec.mode.value,
                    image=PLACED if base is None else base.image,
                )
                results = await self._checks(transport, workspace, request, tree, prepared)
            finally:
                await self._placed.destroy(ctx, instance, spec)
        return ExecutorReport(
            executor=f"executor:{instance}",
            prepared=prepared,
            results=results,
            sha256=digest(results),
        )

    async def _checks(
        self,
        transport: TransportInterface,
        workspace: AgentWorkspace,
        request: ExecutionRequest,
        tree: bytes,
        prepared: Prepared,
    ) -> bytes:
        """Every trial the request asks for, each check's stopping where its
        rate's rule stops it, and their results streams, one after another,
        in `workspace` through `transport`. A trial failed unless its run
        passed, as `ExecutionRecord.passing` says."""
        locked, guarded = _protected(tree, request.protected + request.untouched)
        await transport.write_file(workspace, ARCHIVE, tree, EPOCH)
        unpacked = await self._command(
            transport,
            workspace,
            ("sh", "-c", UNPACK, "sh", TREE, OUT, ARCHIVE),
            ".",
            self._options.setup_time,
        )
        if unpacked.exit_code != 0 or not unpacked.stdout.strip():
            raise Unavailable(f"the tree did not unpack in its instance: {unpacked.stderr[-300:]}")
        root = unpacked.stdout.strip().splitlines()[-1]
        if locked:
            made = await self._command(
                transport,
                workspace,
                ("sh", "-c", LOCK, "sh", *locked),
                TREE,
                self._options.setup_time,
            )
            if made.exit_code != 0:
                raise Unavailable(
                    f"the paths the run protects stayed writable in its instance: "
                    f"{made.stderr[-300:]}"
                )
        sealed = await self._seen(transport, workspace, guarded)
        if guarded and sealed is None:
            raise Unavailable("the instance did not show what it holds at the paths it protects")
        streams: list[bytes] = []
        read = 0
        rates = request.rates or (None,) * len(request.checks)
        for index, (check, trials, rate) in enumerate(
            zip(request.checks, request.trials, rates, strict=True)
        ):
            failed: list[bool] = []
            for trial in range(trials):
                if rate is not None and stops_at(rate, failed, rate.confidence) is not None:
                    break
                out = f"{OUT}/{index}-{trial}.jsonl"
                stream, record = await self._trial(
                    transport,
                    workspace,
                    request,
                    check,
                    prepared,
                    f"{root}/{out}",
                    out,
                    read,
                    (guarded, sealed),
                )
                read += len(stream)
                failed.append(not record.passing)
                streams.append(stream.rstrip(b"\n"))
        return b"\n".join(streams)

    async def _trial(
        self,
        transport: TransportInterface,
        workspace: AgentWorkspace,
        request: ExecutionRequest,
        check: CheckDeclaration,
        prepared: Prepared,
        out: str,
        path: str,
        read: int,
        seal: tuple[tuple[str, ...], str | None],
    ) -> tuple[bytes, ExecutionRecord]:
        """One trial of `check`: its template filled, with `out` where the
        command writes its results stream, and run in the tree; the stream
        read back from `path`, the same file from the instance's root,
        within what is left of the bound; and the run it holds. A trial
        that ran past its time, changed a path the run protects (`seal`
        holds those paths, and their digest before the first trial),
        wrote no stream, one past the bound or longer than one read of the
        transport carries (such as the relay's into a tenant's wall), or
        one the collector does not read as one run of `check` at the
        version asked, ran to no verdict: its stream is an `errored` run
        the executor writes in its place."""
        argv = tuple(part.format(version=request.version, out=out) for part in check.command)
        started = self._clock()
        ran = await self._command(transport, workspace, argv, TREE, self._options.trial_time)
        left = self._options.max_results_bytes - read
        stream, why = b"", None
        guarded, sealed = seal
        if ran.timed_out:
            why = "ran past its time"
        elif await self._seen(transport, workspace, guarded) != sealed:
            why = "changed a path the run protects"
        else:
            try:
                stream = await transport.read_file(workspace, path, max(left, 0) + 1)
            except InfraException as failed:
                if failed.http_status not in (MISSING, TOO_LARGE):
                    raise
                why = f"wrote no results stream it could be read by ({failed.message})"
            else:
                if len(stream) > left:
                    why = f"wrote results past the {self._options.max_results_bytes} bytes a run reads"
        if why is None:
            try:
                records = collect(
                    stream,
                    executor="executor",
                    agent_session_id=request.agent_session_id,
                    agent_project=request.agent_project,
                    purpose=request.purpose,
                    validation_id=new_id(),
                    now=self._clock(),
                    prepared=prepared,
                )
            except ValidationFailed as refused:
                why = refused.message
            else:
                if len(records) == 1 and _asked(records[0], check, request.version):
                    return stream, records[0]
                why = f"wrote {len(records)} runs, not one run of {check.name} at the version asked"
        log.warning(
            "a trial of %s for session %s ran to no verdict: %s",
            check.name,
            request.agent_session_id,
            why[:300],
        )
        stream = _errored(check, request.version, prepared, started, self._clock())
        (record,) = collect(
            stream,
            executor="executor",
            agent_session_id=request.agent_session_id,
            agent_project=request.agent_project,
            purpose=request.purpose,
            validation_id=new_id(),
            now=self._clock(),
            prepared=prepared,
        )
        return stream, record

    async def _command(
        self,
        transport: TransportInterface,
        workspace: AgentWorkspace,
        argv: tuple[str, ...],
        cwd: str,
        time: timedelta,
    ) -> CommandResult:
        command = CommandSpec(
            argv=argv,
            cwd=cwd,
            key=new_id(),
            epoch=EPOCH,
            deadline=self._clock() + time,
            max_output=SPOKEN,
            effect="unsafe",
        )
        return await transport.run(workspace, command, seal=SEAL)

    async def _seen(
        self, transport: TransportInterface, workspace: AgentWorkspace, paths: tuple[str, ...]
    ) -> str | None:
        """The digest `SEEN` answers for `paths`, in the tree; None when there
        are none, or when one is gone or the instance cannot tell."""
        if not paths:
            return None
        seen = await self._command(
            transport, workspace, ("sh", "-c", SEEN, "sh", *paths), TREE, self._options.setup_time
        )
        answer = seen.stdout.strip()
        return answer if seen.exit_code == 0 and answer else None


def _protected(tree: bytes, patterns: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The paths of `tree` a pattern of `patterns` matches, as its tar names
    them, and never a folder: the files made read-only, then those with
    every link among them, which the digest covers. A link is never
    followed: its own inode is what the digest reads. A folder stays
    writable, and a new file a check writes in one changes no digest."""
    if not patterns:
        return (), ()
    try:
        with tarfile.open(fileobj=io.BytesIO(tree)) as archive:
            members = archive.getmembers()
    except tarfile.TarError as unread:
        raise Unavailable(f"the tree is no tar the executor reads: {unread}") from None
    held = (member.name for member in members if not member.isdir())
    guarded = protected_paths(patterns, held)
    lockable = {member.name for member in members if member.isfile()}
    return tuple(path for path in guarded if path in lockable), guarded


def _asked(record: ExecutionRecord, check: CheckDeclaration, version: str) -> bool:
    """Whether a run is of `check`, at its version, and ran at `version`."""
    return (record.check, record.check_version, record.version) == (
        check.name,
        check.version,
        version,
    )


def _errored(
    check: CheckDeclaration,
    version: str,
    prepared: Prepared,
    started: datetime,
    finished: datetime,
) -> bytes:
    """The results stream of a trial that ran to no verdict, as the executor
    writes it: one `errored` run of `check` at `version`, on what it made."""
    lines = (
        {
            "kind": "start",
            "schema_version": check.schema_version,
            "check": check.name,
            "check_version": check.version,
            "version": version,
            "dirty": False,
            "environment": {"image": prepared.image},
            "host": prepared.host,
            "isolation": prepared.isolation,
            "started_at": started.isoformat(),
        },
        {
            "kind": "end",
            "outcome": RunOutcome.ERRORED.value,
            "finished_at": max(started, finished).isoformat(),
        },
    )
    return "\n".join(json.dumps(line) for line in lines).encode()
