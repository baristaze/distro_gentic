"""The platform's fresh executor, over its own workspaces. Each run gets an
instance nobody used before, made for that run alone under an id of its
own, and destroyed when the run ends, whatever ended it: nothing of one run
is there for the next.

The tree comes in from outside: the delivered commit with the checks,
fixtures, and runner taken from the protected source, read from the
project's repository by the platform (`Tree`) and written in as files. No
credential and no history enters the instance, and nothing leaves it: its
egress is none. Each check's
command template runs with `{version}` and `{out}` filled, in the tree,
under the environment of the instance's image and its transport, never one
an agent set. Each trial's results stream is read back within the bound,
and the executor hashes what it read.

The instance is the cloud's, made by the provider and reached by the
transport the platform's own processes hold. A session inside its tenant's
wall never runs on them: its checks are refused here, loudly."""

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import Field

from acme.infra.exceptions import InfraException
from acme.infra.transports import CommandResult, CommandSpec, RecordSeal, TransportInterface
from acme.infra.workspaces import (
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationSpec,
    ResourceLimits,
    Workspace,
    WorkspaceProviderInterface,
)
from acme.om.base import Platform, new_id, utcnow
from acme.om.context import TenantContext
from acme.om.evidence.collector import digest
from acme.om.evidence.executor import ExecutorInterface
from acme.om.evidence.rates import stops_at
from acme.om.evidence.types.contract import SCHEMAS, CheckDeclaration, Offer
from acme.om.evidence.types.validation import ExecutionRequest, ExecutorReport
from acme.om.exceptions import Unavailable, ValidationFailed

ARCHIVE = "tree.tar"
"""Where the tree's tar is written in the instance, until it is unpacked."""
TREE = "tree"
"""Where the tree is unpacked, under the instance's root: the checks run here."""
OUT = "out"
"""Where each trial's results stream goes, beside the tree, never in it."""
UNPACK = 'mkdir -p "$1" "$2" && tar -xf "$3" -C "$1" && rm -f "$3" && pwd'
"""Unpacks the tree and answers the instance's root, as its commands see it."""
EPOCH = 1
"""The one epoch of an instance's commands: no other run ever reaches it."""
Tree = Callable[[TenantContext, UUID, str, str, tuple[str, ...]], Awaitable[bytes]]
"""The tree a validation of a project runs on, as a tar, by the project, the
commit, the protected source, and the protected patterns: the workspaces'
(`WorkspacesManagerInterface.checks_tree`)."""
MISSING = 404
"""The status a transport answers for a file the instance does not hold."""
SPOKEN = 10_000
"""The most of a command's own output kept: a check writes its results to
`{out}`, never to its output."""


class ExecutorOptions(Platform):
    # The isolation each instance is made at: a container, as the cloud's
    # executors are.
    isolation: IsolationMode = IsolationMode.CONTAINER
    limits: ResourceLimits = ResourceLimits()
    # What the instance's image offers a check, as its declaration names it.
    capabilities: frozenset[str] = frozenset()
    # How long the tree's unpacking may take, and one trial of a check.
    setup_time: timedelta = timedelta(minutes=5)
    trial_time: timedelta = timedelta(minutes=20)
    # The most of a run's results streams read back, all trials together.
    max_results_bytes: int = Field(default=64 * 1024 * 1024, gt=0)


async def _kept_nowhere(data: bytes) -> bytes | None:
    """An instance's commands keep no output at rest: it goes with the
    instance."""
    return None


SEAL = RecordSeal(seal=_kept_nowhere, open=_kept_nowhere)


class ExecutorWorkspacesImpl(ExecutorInterface):
    def __init__(
        self,
        provider: WorkspaceProviderInterface,
        transport: TransportInterface,
        tree: Tree,
        inside_wall: Callable[[UUID, UUID], Awaitable[bool]],
        options: ExecutorOptions | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._provider = provider
        self._transport = transport
        self._tree = tree
        self._inside_wall = inside_wall
        self._options = options or ExecutorOptions()
        self._clock = clock

    async def offer(self, ctx: TenantContext) -> Offer:
        return Offer(capabilities=self._options.capabilities, schemas=SCHEMAS)

    async def run(self, ctx: TenantContext, request: ExecutionRequest) -> ExecutorReport:
        if await self._inside_wall(ctx.org_id, request.session_id):
            raise Unavailable(
                f"session {request.session_id} runs inside its tenant's wall, "
                "so its checks never run on the platform's machines"
            )
        try:
            project_id = UUID(request.project)
        except ValueError:
            raise Unavailable(f"{request.project} is no project's id to validate") from None
        tree = await self._tree(ctx, project_id, request.version, request.source, request.protected)
        instance = new_id()
        spec = IsolationSpec(
            mode=self._options.isolation,
            egress=EgressPolicy(mode=EgressMode.NONE),
            limits=self._options.limits,
        )
        try:
            workspace = await self._provider.prepare(ctx.org_id, instance, spec)
            results = await self._checks(workspace, request, tree)
        finally:
            await self._provider.purge(ctx.org_id, instance)
            await self._transport.purge_records(instance)
        return ExecutorReport(
            executor=f"executor:{instance}", results=results, sha256=digest(results)
        )

    async def _checks(self, workspace: Workspace, request: ExecutionRequest, tree: bytes) -> bytes:
        """Every trial the request asks for, each check's stopping where its
        rate's rule stops it, and their results streams, one after another."""
        await self._transport.write_file(workspace, ARCHIVE, tree, EPOCH)
        unpacked = await self._command(
            workspace, ("sh", "-c", UNPACK, "sh", TREE, OUT, ARCHIVE), ".", self._options.setup_time
        )
        if unpacked.exit_code != 0 or not unpacked.stdout.strip():
            raise Unavailable(f"the tree did not unpack in its instance: {unpacked.stderr[-300:]}")
        root = unpacked.stdout.strip().splitlines()[-1]
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
                stream = await self._trial(workspace, request, check, f"{root}/{out}", out, read)
                read += len(stream)
                failed.append(_ended(stream) != "passed")
                streams.append(stream.rstrip(b"\n"))
        return b"\n".join(streams)

    async def _trial(
        self,
        workspace: Workspace,
        request: ExecutionRequest,
        check: CheckDeclaration,
        out: str,
        path: str,
        read: int,
    ) -> bytes:
        """One trial of `check`: its template filled, with `out` where the
        command writes its results stream, and run in the tree; and the
        stream read back from `path`, the same file from the instance's root,
        within what is left of the bound. A check that wrote none is refused: a run nobody can read is
        no evidence."""
        argv = tuple(part.format(version=request.version, out=out) for part in check.command)
        await self._command(workspace, argv, TREE, self._options.trial_time)
        left = self._options.max_results_bytes - read
        try:
            stream = await self._transport.read_file(workspace, path, left + 1)
        except InfraException as failed:
            if failed.http_status != MISSING:
                raise
            raise ValidationFailed(f"{check.name} wrote no results stream") from None
        if len(stream) > left:
            raise ValidationFailed(
                f"the results are past the {self._options.max_results_bytes} bytes a run reads"
            )
        return stream

    async def _command(
        self, workspace: Workspace, argv: tuple[str, ...], cwd: str, time: timedelta
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
        return await self._transport.run(workspace, command, seal=SEAL)


def _ended(stream: bytes) -> str | None:
    """How a trial's run ended, as its last line says; None when it says
    nothing readable, which a rate counts as a failure."""
    lines = stream.strip().splitlines()
    try:
        last = json.loads(lines[-1]) if lines else None
    except ValueError:
        return None
    if not isinstance(last, dict) or last.get("kind") != "end":
        return None
    outcome = last.get("outcome")
    return outcome if isinstance(outcome, str) else None
