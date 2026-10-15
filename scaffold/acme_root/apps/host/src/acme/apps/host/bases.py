"""A workspace's base as a host builds and keeps it: the image an agent project's
workspace base names and its setup, built once on this host and kept in the
host's own store, inside its owner's wall, as its snapshots are. Nothing of
it reaches the platform: a prepare on a base starts the workspace from the
store's copy.

A base is built where its workspaces run, by the provider that runs them.
Its setup runs in a workspace of its own, on the base's image, with the
setup's egress, through the host's transport: as `sh -c`, with no secret
and no variable of its own, and what a command printed is not kept. No
model runs, and nothing of a session or of the tenant's records is in it.
The build's workspace and its records go however it ends. The snapshot is
scanned for the values of the secrets this host keeps for the tenant, and
one that holds a value is not kept.

A build outlasts the claim of the prepare that asked for it, so it runs
beside the prepares: one that finds the base being built waits a while,
then is refused with a refusal that clears, and the platform asks again. A
build that fails keeps nothing, and its reason answers each prepare of
that base for a while, a command too long for a refusal on the wire cut
to fit; after that, the next prepare builds again. One build
a base, on this host: hosts of a pool that share a store share its bases."""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

from acme.apps.host.snapshots import HostSnapshots, SnapshotHeldSecret
from acme.infra.agent_workspaces import (
    AgentWorkspaceBase,
    AgentWorkspaceProviderInterface,
    BaseSetupFailed,
    Durability,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
)
from acme.infra.exceptions import InfraException
from acme.infra.transports import CommandSpec, RecordSeal, TransportInterface, secret_held

log = logging.getLogger(__name__)

BUILD_LIMIT = timedelta(minutes=30)
"""How long a build may run, its setup's commands together."""

BUILD_WAIT = timedelta(seconds=20)
"""How long a prepare waits on a build before it is refused, so the work's
claim, a minute long, never runs out under it."""

FAILURE_KEPT = timedelta(minutes=10)
"""How long a failed build answers the prepares of its base before the
next one builds again."""

REFUSAL_LIMIT = 2000
"""The most characters a prepare's refusal carries on the wire."""

KEPT_UNDER = uuid.UUID("8f1d3c52-6b0e-4f7a-9a41-5c2e7d9b0a13")
"""The namespace of the workspace a provider keeps a base under, when it
keeps one outside its snapshot, such as a disk."""


class BaseUnbuilt(Exception):
    """The base failed to build on this host: a setup command failed, or its
    snapshot held a secret's value, or the provider failed. Nothing of it is
    kept. Names why, never a secret's value."""


def base_key(spec: IsolationSpec) -> str:
    """The base `spec` names, as this host's store keeps it: a SHA-256 of the
    mode its workspaces run in and of the base whole, its image, its
    commands, and its egress. A changed base is another key."""
    named = {"mode": spec.mode.value, "base": None}
    if spec.base is not None:
        named["base"] = spec.base.model_dump(mode="json")
    return hashlib.sha256(json.dumps(named, sort_keys=True).encode()).hexdigest()


def setup_failed(index: int, command: str, exit_code: int | None) -> BaseSetupFailed:
    """The failure of the setup's command `index`, its text cut with a marker
    where the whole would not fit a refusal on the wire, so the command's
    start and how it ended always reach the platform."""
    failed = BaseSetupFailed(index, command, exit_code)
    kept = len(command)
    while len(failed.message) > REFUSAL_LIMIT and kept > 0:
        marker = f"…[{len(command) - kept} more characters]"
        kept = max(kept - (len(failed.message) - REFUSAL_LIMIT) - len(marker) - 1, 0)
        cut = f"{command[:kept]}…[{len(command) - kept} more characters]"
        failed = BaseSetupFailed(index, cut, exit_code)
    return failed


async def _unkept(data: bytes) -> None:
    return None


UNKEPT = RecordSeal(seal=_unkept, open=_unkept)
"""A setup's output is not kept: its record says how it ended alone."""


class HostBases:
    """The bases of this host's store, built by its providers and transports,
    each by the isolation mode it runs."""

    def __init__(
        self,
        store: HostSnapshots,
        workspaces: Mapping[IsolationMode, AgentWorkspaceProviderInterface],
        transports: Mapping[IsolationMode, TransportInterface],
        *,
        build_limit: timedelta = BUILD_LIMIT,
        wait: timedelta = BUILD_WAIT,
        failure_kept: timedelta = FAILURE_KEPT,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._agent_workspaces = workspaces
        self._transports = transports
        self._build_limit = build_limit
        self._wait = wait
        self._failure_kept = failure_kept
        self._clock = clock
        self._monotonic = monotonic
        self._building: dict[tuple[UUID, str], asyncio.Task[None]] = {}
        self._failed: dict[tuple[UUID, str], tuple[str, float]] = {}

    async def archive(self, org_id: UUID, spec: IsolationSpec) -> bytes:
        """The snapshot of the base `spec` names, from this host's store, or
        built when the store holds none. `IsolationRefused`, which clears,
        while the build runs past the wait; `BaseUnbuilt` with its reason
        when the build failed."""
        key = base_key(spec)
        kept = await self._read(org_id, spec, key)
        if kept is not None:
            return kept
        build = self._building.get((org_id, key))
        if build is None:
            build = asyncio.create_task(self._built(org_id, spec, key))
            self._building[(org_id, key)] = build
        try:
            await asyncio.wait_for(asyncio.shield(build), self._wait.total_seconds())
        except TimeoutError:
            raise IsolationRefused(
                "this host is building the workspace's base: its setup runs "
                f"{len(spec.base.setup) if spec.base else 0} commands",
                clears=True,
            ) from None
        kept = await self._read(org_id, spec, key)
        if kept is None:
            raise IsolationRefused("this host did not keep the workspace's base", clears=True)
        return kept

    async def kept(self, org_id: UUID, spec: IsolationSpec) -> bytes | None:
        """The snapshot of the base `spec` names when this host's store keeps
        it, or None; never built here."""
        return await self._store.load_base(org_id, base_key(spec))

    async def drop(self, org_id: UUID, spec: IsolationSpec) -> None:
        """The base `spec` names goes from the store, and what its provider
        keeps of it, so the next prepare builds it again."""
        key = base_key(spec)
        provider = self._agent_workspaces.get(spec.mode)
        if provider is not None:
            await provider.purge(org_id, uuid.uuid5(KEPT_UNDER, f"{org_id}/{key}"))
        await self._store.drop_base(org_id, key)

    async def _read(self, org_id: UUID, spec: IsolationSpec, key: str) -> bytes | None:
        """The kept base, or None; `BaseUnbuilt` while a failed build's
        reason still answers for it."""
        kept = await self._store.load_base(org_id, key)
        if kept is not None:
            return kept
        failed = self._failed.get((org_id, key))
        if failed is not None:
            reason, until = failed
            if self._monotonic() < until:
                raise BaseUnbuilt(reason)
            del self._failed[(org_id, key)]
        return None

    async def _built(self, org_id: UUID, spec: IsolationSpec, key: str) -> None:
        """One build, its failure kept as its reason."""
        try:
            await self._build(org_id, spec, key)
            self._failed.pop((org_id, key), None)
        except (InfraException, SnapshotHeldSecret, OSError) as error:
            reason = error.message if isinstance(error, InfraException) else str(error)
            log.warning("the workspace base %s of org %s is not kept: %s", key, org_id, reason)
            until = self._monotonic() + self._failure_kept.total_seconds()
            self._failed[(org_id, key)] = (reason, until)
        finally:
            self._building.pop((org_id, key), None)

    async def _build(self, org_id: UUID, spec: IsolationSpec, key: str) -> None:
        """The setup run in a workspace of its own, on the base's image with
        the setup's egress and what a package manager needs (`building`),
        then snapshotted, scanned, and kept."""
        base = spec.base
        provider = self._agent_workspaces.get(spec.mode)
        transport = self._transports.get(spec.mode)
        if base is None or provider is None or transport is None:
            raise IsolationRefused(f"this host builds no base of a {spec.mode.value} workspace")
        setup = spec.model_copy(
            update={
                "egress": base.egress,
                "durability": Durability.SNAPSHOT,
                "base": AgentWorkspaceBase(image=base.image),
            }
        )
        build_id = uuid.uuid4()
        kept_under = uuid.uuid5(KEPT_UNDER, f"{org_id}/{key}")
        deadline = self._clock() + self._build_limit
        try:
            workspace = await provider.prepare(org_id, build_id, setup, building=True)
            for index, command in enumerate(base.setup):
                ran = await transport.run(
                    workspace,
                    CommandSpec(
                        argv=("sh", "-c", command), key=uuid.uuid4(), epoch=0, deadline=deadline
                    ),
                    seal=UNKEPT,
                )
                if ran.exit_code != 0:
                    raise setup_failed(index, command, ran.exit_code)
            taken = await provider.snapshot(workspace)
            archive = await provider.keep(taken, org_id, kept_under)
        finally:
            await provider.purge(org_id, build_id)
            await transport.purge_records(build_id)
        try:
            values = await self._store.values(org_id)
            found = await secret_held(provider.held(archive), values)
            if found is not None:
                raise SnapshotHeldSecret(
                    f"the workspace's base holds the secret {found!r}, so it is not kept"
                )
            await self._store.keep_base(org_id, key, archive)
        except BaseException:
            await provider.purge(org_id, kept_under)
            raise
        log.info("the workspace base %s of org %s is kept in this host's store", key, org_id)
