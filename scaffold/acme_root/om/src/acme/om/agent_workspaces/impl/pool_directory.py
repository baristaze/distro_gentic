"""The directory of a VM of the cloud pool, packed, read out, and brought
back through the transport that reaches its host: the exec relay, since
the platform never calls into the VM. It is how the platform's tools keep
the files of a session the pool runs, as the engine's VM provider keeps
its VM's (`acme.infra.agent_workspaces.packs`, ADR 1045): the tools seal
the parts and keep them (`pool_archive`), and this module moves them (ADR
2070, ADR 2077).

A relayed file operation reaches the workspace's directory alone, so the
pack sits in a folder of the directory's own, `KEPT`, which no archive
holds and no measure counts, and which is gone once the pack is dropped
or the directory restored. The name is the pool's: a folder a command
made under it goes at the next pack.

A pack measures the directory by the bytes its files hold and refuses one
past the bound before tar starts, naming both. It is one tar archive,
compressed with zstd where the VM has it, measured before any byte of it
leaves, and read out in parts, one relayed read each, from its offset. The
runner reads the tar out of it only to scan it, a part at a time, and never
past the bound (`unpacked`). A restore puts the parts into `KEPT`: the VM's
host fetches them from the store itself, by a link each, `FETCHED` at a
time (`fetch`); for a host that cannot, and for an archive kept before,
each is one relayed write (`write`). Each is bounded as any relayed
operation is. Then the directory is emptied around them and filled from
them in order: the unpack's bound counts from its own start, so a large
archive's move never spends it. Each runs as the VM's root where its user
may become root without a password; elsewhere, as its user, and a file
that user cannot read refuses the pack."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterable, Sequence
from compression.zstd import ZstdDecompressor, ZstdError
from datetime import datetime, timedelta
from typing import Literal, cast, get_args

from acme.infra.agent_workspaces import (
    AgentWorkspace,
    AgentWorkspaceLost,
    DirectoryPack,
    SnapshotRefused,
)
from acme.infra.buckets.sealed import ObjectRefused
from acme.infra.exceptions import BackendFailed, InfraException
from acme.infra.transports import CommandResult, CommandSpec, RecordSeal, TransportInterface
from acme.om.base import new_id
from acme.om.context import TenantContext
from acme.om.exec_relay.exceptions import FetchNotRead
from acme.om.exec_relay.types.exec import FETCHED, FetchesKept, KeptFile, ObjectRef
from acme.om.tools.seal import RecordSealInterface

__all__ = [
    "KEPT",
    "PACKED",
    "TAR",
    "TAR_ZSTD",
    "Packing",
    "drop",
    "fetch",
    "pack",
    "read",
    "unpack",
    "unpacked",
    "write",
]

KEPT = ".acme-kept"
"""The folder at the top of the directory that holds a pack, or the parts
a restore brings, and nothing of the session's."""

PACKED = f"{KEPT}/pack"
"""Where a pack is written in the directory."""

Packing = Literal["tar", "tar+zstd"]
"""How a pack holds the directory: one tar archive, or one compressed with
zstd."""

TAR: Packing = "tar"
TAR_ZSTD: Packing = "tar+zstd"

AS_ROOT = 'as=; if [ "$(id -u)" != 0 ] && sudo -n true 2>/dev/null; then as="sudo -n"; fi'
"""Root where the VM's user may become it without a password, as the
engine's packs run."""

PAST = 3
"""The pack script's exit when the directory holds more than the bound."""

PACK = f"""set -u
{AS_ROOT}
held=$($as find . -path ./{KEPT} -prune -o -type f -exec wc -c {{}} + \\
  | awk '!(NF == 2 && $2 == "total") {{ s += $1 }} END {{ printf "%.0f\\n", s }}')
if [ "$held" -gt "$1" ]; then printf '%s\\n' "$held"; exit {PAST}; fi
$as rm -rf ./{KEPT} || exit 70
mkdir -m 700 ./{KEPT} || exit 70
if command -v zstd >/dev/null 2>&1; then
  packing={TAR_ZSTD}
  {{ $as tar --numeric-owner --exclude=./{KEPT} -cf - .; echo $? > ./{KEPT}/tarred; }} \\
    | zstd -q -T0 -c > ./{PACKED}
  if [ $? -ne 0 ]; then rm -rf ./{KEPT}; exit 70; fi
  code=$(cat ./{KEPT}/tarred) || exit 70
else
  packing={TAR}
  $as tar --numeric-owner --exclude=./{KEPT} -cf - . > ./{PACKED}
  code=$?
fi
if [ "$code" -gt 1 ]; then rm -rf ./{KEPT}; exit "$code"; fi
size=$(wc -c < ./{PACKED}) || exit 70
printf '%s %s\\n' "$packing" $size
"""
"""The directory measured by the bytes its files hold, `KEPT` aside, and
refused past the bound `$1`; else packed at `PACKED`, compressed where the
VM has zstd, and how it is packed with its size. Tar's exit 1 says a file
changed while it was read: the pack holds it as read."""

UNPACK = f"""set -u
{AS_ROOT}
held=$(find ./{KEPT} -maxdepth 1 -type f -name 'part-*' | wc -l)
if [ "$held" -ne "$1" ]; then exit 65; fi
$as find . -mindepth 1 -maxdepth 1 ! -name {KEPT} -exec rm -rf {{}} + || exit $?
if [ "$2" = {TAR_ZSTD} ]; then
  {{ cat ./{KEPT}/part-* | zstd -q -d -c; echo $? > ./{KEPT}/unzipped; }} \\
    | $as tar --numeric-owner -xf - || exit $?
  [ "$(cat ./{KEPT}/unzipped)" = 0 ] || exit 74
else
  cat ./{KEPT}/part-* | $as tar --numeric-owner -xf - || exit $?
fi
$as rm -rf ./{KEPT}
"""
"""The directory emptied around `KEPT`, then filled from the `$1` parts
brought there, in order, as `$2` packed them, and `KEPT` gone."""

UNPACKED_BYTES = 1024 * 1024
"""The most bytes of a compressed pack's tar the runner holds at a time."""


def part_path(index: int) -> str:
    """Where a restore brings a part, named so the parts sort in order."""
    return f"{KEPT}/part-{index:06d}"


async def pack(
    ctx: TenantContext,
    transport: TransportInterface,
    record_seal: RecordSealInterface,
    workspace: AgentWorkspace,
    *,
    bound: int,
    epoch: int,
    within: timedelta,
    now: datetime,
) -> tuple[DirectoryPack, Packing]:
    """The workspace's directory packed at `PACKED`, measured, and how it
    is packed: nothing of it has left the VM yet. One whose files hold more
    than `bound` bytes is refused (`SnapshotRefused`) before it is packed.
    A pack that fails, or takes longer than `within`, is refused; its
    caller drops what is left."""
    ended = await _run(
        ctx, transport, record_seal, workspace, PACK, (str(bound),), epoch, within, now
    )
    if ended.exit_code == PAST:
        raise SnapshotRefused(
            f"the workspace's directory holds {ended.stdout.strip()} bytes, "
            f"past the bound of {bound}, so no snapshot is kept"
        )
    _completed(ended, "pack", within)
    try:
        packing, measured = ended.stdout.split()
        size = int(measured)
    except ValueError as error:
        raise BackendFailed("directory", "pack", f"the pack is not measured: {error}") from error
    if packing not in get_args(Packing):
        raise BackendFailed("directory", "pack", f"the pack is {packing!r}, no packing known")
    pack = DirectoryPack(location=workspace.location, path=PACKED, size=size)
    return pack, cast(Packing, packing)


async def read(
    transport: TransportInterface, workspace: AgentWorkspace, pack: DirectoryPack, part_bytes: int
) -> AsyncGenerator[bytes]:
    """The pack's bytes, in parts of `part_bytes`, the last one shorter, each
    one relayed read from its offset. A part shorter than it should be
    is an error, never the end of the pack."""
    if part_bytes <= 0:
        raise ValueError("a part holds at least one byte")
    offset = 0
    while offset < pack.size:
        want = min(part_bytes, pack.size - offset)
        part = await transport.read_file(workspace, pack.path, want, offset)
        if len(part) != want:
            raise BackendFailed(
                "directory", "read", f"the pack read {len(part)} bytes at {offset}, not {want}"
            )
        yield part
        offset += want


async def unpacked(
    parts: AsyncIterable[bytes], packing: Packing, bound: int
) -> AsyncGenerator[bytes]:
    """The tar a pack holds, as `parts` read it out: decompressed a slice
    at a time, never whole, and refused (`SnapshotRefused`) once it passes
    `bound` bytes, the most a directory's archive may hold, or when it does
    not decompress whole."""
    if packing == TAR:
        async for part in parts:
            yield part
        return
    held = 0
    decompressor = ZstdDecompressor()
    try:
        async for part in parts:
            data = part
            while True:
                if decompressor.eof:
                    # The next frame, as a stream compressed in frames holds.
                    data = decompressor.unused_data + data
                    if not data:
                        break
                    decompressor = ZstdDecompressor()
                tar = await asyncio.to_thread(decompressor.decompress, data, UNPACKED_BYTES)
                data = b""
                held += len(tar)
                if held > bound:
                    raise SnapshotRefused(
                        f"the workspace's directory unpacks past the bound of {bound}, "
                        "so no snapshot is kept"
                    )
                if tar:
                    yield tar
                if decompressor.needs_input and not decompressor.eof:
                    break
    except ZstdError as error:
        raise SnapshotRefused(f"the workspace's pack does not decompress: {error}") from error
    if not decompressor.eof:
        raise SnapshotRefused("the workspace's pack ends part way through")


async def drop(
    ctx: TenantContext,
    transport: TransportInterface,
    record_seal: RecordSealInterface,
    workspace: AgentWorkspace,
    *,
    epoch: int,
    within: timedelta,
    now: datetime,
) -> None:
    """The pack removed from the directory; one already gone is no error."""
    ended = await _run(
        ctx, transport, record_seal, workspace, f"rm -rf ./{KEPT}", (), epoch, within, now
    )
    _completed(ended, "drop", within)


async def fetch(
    transport: TransportInterface,
    workspace: AgentWorkspace,
    parts: Sequence[ObjectRef],
    *,
    epoch: int,
) -> None:
    """Each of the archive's parts brought into `KEPT` by the VM's host
    itself, from the store, `FETCHED` at a time, each by a link signed for
    it alone and opened by its own key there: no byte of them crosses this
    process. A transport or a host that fetches none is refused before
    anything is sent (`FetchNotRead`). A part its host refused, one that
    did not open or match its size and its digest, loses the restore
    (`AgentWorkspaceLost`)."""
    if not isinstance(transport, FetchesKept):
        raise FetchNotRead(f"{transport.describe()} fetches no file the store keeps")
    files = [KeptFile(path=part_path(index), object=part) for index, part in enumerate(parts)]
    for start in range(0, len(files), FETCHED):
        try:
            await transport.fetch_files(workspace, files[start : start + FETCHED], epoch)
        except InfraException as error:
            if error.code != ObjectRefused.code:
                raise
            raise AgentWorkspaceLost(
                f"a part of the archive did not reach the VM whole: {error.message}"
            ) from error


async def write(
    transport: TransportInterface,
    workspace: AgentWorkspace,
    parts: AsyncIterable[bytes],
    *,
    epoch: int,
) -> int:
    """Each part `parts` holds, in order, written into `KEPT` as one relayed
    write, and how many there were. An error `parts` raises ends it and is
    raised as it is."""
    count = 0
    async for part in parts:
        await transport.write_file(workspace, part_path(count), part, epoch)
        count += 1
    return count


async def unpack(
    ctx: TenantContext,
    transport: TransportInterface,
    record_seal: RecordSealInterface,
    workspace: AgentWorkspace,
    *,
    parts: int,
    packing: Packing,
    epoch: int,
    within: timedelta,
    now: datetime,
) -> None:
    """The workspace's directory emptied and filled from the `parts` parts
    a restore brought into `KEPT`, as `packing` packed them, within `within`
    of `now`. One that fails leaves what it did for its caller, whose VM
    goes with it."""
    ended = await _run(
        ctx,
        transport,
        record_seal,
        workspace,
        UNPACK,
        (str(parts), packing),
        epoch,
        within,
        now,
    )
    _completed(ended, "unpack", within)


async def _run(
    ctx: TenantContext,
    transport: TransportInterface,
    record_seal: RecordSealInterface,
    workspace: AgentWorkspace,
    script: str,
    arguments: tuple[str, ...],
    epoch: int,
    within: timedelta,
    now: datetime,
) -> CommandResult:
    """One script in the directory under the run's `epoch`, its record
    sealed under the session's key as any command's is."""
    key = new_id()
    command = CommandSpec(
        argv=("sh", "-c", script, "sh", *arguments),
        key=key,
        epoch=epoch,
        deadline=now + within,
        effect="idempotent",
    )
    seal = RecordSeal(
        seal=lambda data: record_seal.seal(ctx, workspace.id, key, data),
        open=lambda sealed: record_seal.open(ctx, workspace.id, key, sealed),
    )
    return await transport.run(workspace, command, seal=seal)


def _completed(ended: CommandResult, operation: str, within: timedelta) -> None:
    if ended.timed_out or ended.exit_code is None:
        raise BackendFailed(
            "directory",
            operation,
            f"the {operation} did not end within {within.total_seconds():g} seconds",
        )
    if ended.exit_code != 0:
        # Named by its exit, never by what it printed: the names of the
        # session's files are its content.
        raise BackendFailed("directory", operation, f"exit {ended.exit_code}")
