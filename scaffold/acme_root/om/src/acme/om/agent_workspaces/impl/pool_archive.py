"""A session's files as the cloud pool keeps them, beside the engine's
directory snapshots (`acme.om.tools.impl.snapshots`, ADR 1045): the pack
of a VM's directory, in parts, each sealed under a key of its own and bound
to where it is kept (`acme.infra.buckets.sealed`), as an object the exec
relay moves is. The archive names each part by its size, its digest, and
its key, and is kept as any snapshot is, sealed under the session's key
and trusted by its keyed hash: revoking that key leaves every part's key
noise, and the parts with them. So the host of the session's VM fetches and
opens its own session's parts itself, handed each one's key and a link
signed for it alone, and no byte of them crosses the runner (ADR 2077).

An archive kept before is the engine's manifest over a plain tar, its parts
sealed under the session's key: it still restores, each part opened here
and relayed (`SnapshotStore.parts`)."""

import asyncio
import base64
import binascii
import contextlib
import json
import logging
import re
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Collection
from dataclasses import dataclass
from typing import cast, get_args
from uuid import UUID

from acme.infra.agent_workspaces import AgentWorkspaceLost, SnapshotRefused
from acme.infra.buckets import BlobNotFound, BucketsInterface
from acme.infra.buckets.sealed import (
    KEY_BYTES,
    ObjectRefused,
    digest_of,
    new_key,
    open_object,
    seal_object,
)
from acme.infra.exceptions import InfraException
from acme.om.agent_steps.types.header import AgentWorkspaceSnapshot, SnapshotHolds
from acme.om.agent_workspaces.impl.pool_directory import Packing
from acme.om.agent_workspaces.types.snapshot import DIGEST
from acme.om.context import TenantContext
from acme.om.exec_relay.types.exec import ObjectRef
from acme.om.tools.impl.snapshots import BUCKET, CONTENT_TYPE, Manifest, SnapshotStore, part_key

log = logging.getLogger(__name__)

__all__ = ["POOL_FORMAT", "KeptPart", "PoolManifest", "keep", "opened", "parts"]

POOL_FORMAT = "acme.pool-archive/1"
"""What an archive the pool keeps says it is."""


@dataclass(frozen=True)
class KeptPart:
    """A part as its archive names it: the size and the digest of its
    bytes, and the key (base64) it is sealed under, which opens it alone."""

    size: int
    digest: str
    key: str


@dataclass(frozen=True)
class PoolManifest:
    """What an archive the pool keeps names: the id its parts are kept
    under, the pack's size, how it is packed, and each part, in order."""

    snapshot_id: UUID
    size: int
    packing: Packing
    parts: tuple[KeptPart, ...]

    def objects(self, agent_session_id: UUID) -> list[ObjectRef]:
        """Each part as the object the store keeps it as, in order: what the
        host of the session's VM is handed to fetch it."""
        return [
            ObjectRef(
                reference=part_key(agent_session_id, self.snapshot_id, index),
                size=part.size,
                digest=part.digest,
                key=part.key,
            )
            for index, part in enumerate(self.parts)
        ]


def _named(archive: PoolManifest) -> bytes:
    named = {
        "format": POOL_FORMAT,
        "snapshot": str(archive.snapshot_id),
        "size": archive.size,
        "packing": archive.packing,
        "parts": [[part.size, part.digest, part.key] for part in archive.parts],
    }
    return json.dumps(named, sort_keys=True).encode()


def _key(key: str) -> bytes:
    return base64.b64decode(key, validate=True)


def _keyed(key: object) -> bool:
    """Whether `key` is a part's key, as `keep` writes one."""
    try:
        return isinstance(key, str) and len(_key(key)) == KEY_BYTES
    except binascii.Error, ValueError:
        return False


def _read(data: bytes, what: str) -> PoolManifest | None:
    """What `_named` wrote; None for the manifest of an archive kept before,
    the engine's. Anything else loses the workspace that would start from
    it (`AgentWorkspaceLost`)."""
    try:
        named = json.loads(data)
        if named["format"] != POOL_FORMAT:
            return None
        size, packing = named["size"], named["packing"]
        snapshot_id = UUID(named["snapshot"])
        parts = tuple(KeptPart(size=n, digest=digest, key=key) for n, digest, key in named["parts"])
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise AgentWorkspaceLost(f"{what} names no archive's parts: {error}") from error
    if packing not in get_args(Packing):
        raise AgentWorkspaceLost(f"{what} is packed as {packing!r}, which no VM unpacks")
    if not all(
        isinstance(part.size, int)
        and part.size > 0
        and isinstance(part.digest, str)
        and re.match(DIGEST, part.digest) is not None
        and _keyed(part.key)
        for part in parts
    ):
        raise AgentWorkspaceLost(f"{what} names a part by no size, digest, or key")
    if not isinstance(size, int) or sum(part.size for part in parts) != size:
        raise AgentWorkspaceLost(f"{what} names parts that do not add up to its size")
    return PoolManifest(
        snapshot_id=snapshot_id, size=size, packing=cast(Packing, packing), parts=parts
    )


async def keep(
    snapshots: SnapshotStore,
    buckets: BucketsInterface,
    ctx: TenantContext,
    agent_session_id: UUID,
    snapshot_id: UUID,
    agent_workspace_id: UUID,
    *,
    size: int,
    packing: Packing,
    read: Callable[[int], AsyncGenerator[bytes]],
) -> AgentWorkspaceSnapshot:
    """A pack of `size` bytes, as `read` gives it in parts of the store's
    `part_bytes`, kept as the session's snapshot under `snapshot_id`, taken
    of the workspace under `agent_workspace_id`: each part sealed under a
    key of its own, bound to where it is kept, and put there, then the
    archive that names each part with its key, kept as any snapshot is.
    Refused past the bound before any part is read, and when the session
    keeps no content at rest (`SnapshotRefused`). One that fails part way
    removes every part it put, so no step names it and the snapshot before
    stays the latest."""
    snapshots.bounded(size)
    put: list[str] = []
    parts: list[KeptPart] = []
    held = 0
    try:
        async with contextlib.aclosing(read(snapshots.part_bytes)) as stream:
            async for data in stream:
                if held + len(data) > size:
                    raise SnapshotRefused(
                        f"the workspace's directory read past the {size} bytes it packed to"
                    )
                reference = part_key(agent_session_id, snapshot_id, len(parts))
                key = new_key()
                sealed = await asyncio.to_thread(seal_object, key, reference, data)
                put.append(reference)
                await buckets.put(
                    ctx.org_id, BUCKET, reference, sealed, CONTENT_TYPE, deadline=ctx.deadline
                )
                digest = await asyncio.to_thread(digest_of, data)
                parts.append(
                    KeptPart(size=len(data), digest=digest, key=base64.b64encode(key).decode())
                )
                held += len(data)
        if held != size:
            raise SnapshotRefused(
                f"the workspace's directory read short of the {size} bytes it packed to"
            )
        archive = PoolManifest(
            snapshot_id=snapshot_id, size=size, packing=packing, parts=tuple(parts)
        )
        kept = await snapshots.keep(
            ctx, agent_session_id, snapshot_id, agent_workspace_id, _named(archive)
        )
    except BaseException:
        await _remove(buckets, ctx, put)
        raise
    return kept.model_copy(update={"size": size, "holds": SnapshotHolds.DIRECTORY})


async def opened(
    snapshots: SnapshotStore,
    ctx: TenantContext,
    agent_session_id: UUID,
    snapshot: AgentWorkspaceSnapshot,
) -> PoolManifest | Manifest:
    """What a directory's snapshot the session keeps names, trusted only
    once it opens under the session's key and hashes to what its step
    names, and holds the size the step names: an archive the pool keeps, or
    the engine's manifest of one kept before. Anything else loses the
    workspace that would start from it (`AgentWorkspaceLost`)."""
    what = f"snapshot {snapshot.id} of agent session {agent_session_id}"
    archive = _read(await snapshots.load(ctx, agent_session_id, snapshot), what)
    if archive is None:
        return await snapshots.manifest(ctx, agent_session_id, snapshot)
    if archive.size != snapshot.size:
        raise AgentWorkspaceLost(f"{what} does not match its size")
    return archive


async def parts(
    buckets: BucketsInterface, ctx: TenantContext, agent_session_id: UUID, archive: PoolManifest
) -> AsyncIterator[bytes]:
    """The archive's parts, in order, each read from the store here and
    trusted only once it opens under its own key to its size and its
    digest: for a VM whose host fetches none. One gone or altered loses
    the workspace being restored from it (`AgentWorkspaceLost`), and nothing
    kept is touched."""
    for index, part in enumerate(archive.objects(agent_session_id)):
        what = f"part {index} of snapshot {archive.snapshot_id}"
        try:
            sealed = await buckets.get(ctx.org_id, BUCKET, part.reference, deadline=ctx.deadline)
        except InfraException as error:
            if error.code != BlobNotFound.code:
                raise
            raise AgentWorkspaceLost(f"{what} is gone from the store") from error
        try:
            data = await asyncio.to_thread(
                open_object, _key(part.key), part.reference, part.size, part.digest, sealed
            )
        except InfraException as error:
            if error.code != ObjectRefused.code:
                raise
            raise AgentWorkspaceLost(f"{what} does not open to its size and its digest") from error
        yield data


async def _remove(buckets: BucketsInterface, ctx: TenantContext, keys: Collection[str]) -> None:
    """The parts of an archive that was not kept removed. One that cannot be
    is noise, its key in no archive, and goes with the session's purge."""
    for key in keys:
        try:
            await buckets.delete(ctx.org_id, BUCKET, key)
        except Exception:
            log.warning("a part of an archive that was not kept stays: %s", key, exc_info=True)
