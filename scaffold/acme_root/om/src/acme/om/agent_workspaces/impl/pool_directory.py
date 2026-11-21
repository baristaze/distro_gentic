"""The directory of a VM of the cloud pool, packed, read out, and brought
back through the transport that reaches its host: the exec relay, since
the platform never calls into the VM. It is how the platform's tools keep
the files of a session the pool runs, as the engine's VM provider keeps
its VM's (`acme.infra.agent_workspaces.packs`, ADR 1045): the tools seal
the parts and keep them, and this module moves them (ADR 2070).

A relayed file operation reaches the workspace's directory alone, so the
pack sits in a folder of the directory's own, `KEPT`, which no archive
holds and no measure counts, and which is gone once the pack is dropped
or the directory restored. The name is the pool's: a folder a command
made under it goes at the next pack.

A pack measures the directory by the bytes its files hold and refuses one
past the bound before tar starts, naming both. It is one tar archive,
measured before any byte of it leaves, and read out in parts, one relayed
read each, from its offset. A restore writes the parts into `KEPT`, one
relayed write each, then empties the directory around them and unpacks
them into it in order. Each runs as the VM's root where its user may
become root without a password; elsewhere, as its user, and a file that
user cannot read refuses the pack."""

from collections.abc import AsyncGenerator, AsyncIterable
from datetime import datetime, timedelta

from acme.infra.agent_workspaces import AgentWorkspace, DirectoryPack, SnapshotRefused
from acme.infra.agent_workspaces.packs import AS_ROOT, PAST
from acme.infra.exceptions import BackendFailed
from acme.infra.transports import CommandResult, CommandSpec, RecordSeal, TransportInterface
from acme.om.base import new_id
from acme.om.context import TenantContext
from acme.om.tools.seal import RecordSealInterface

__all__ = ["KEPT", "PACKED", "drop", "pack", "read", "unpack"]

KEPT = ".acme-kept"
"""The folder at the top of the directory that holds a pack, or the parts
a restore writes, and nothing of the session's."""

PACKED = f"{KEPT}/pack"
"""Where a pack is written in the directory."""

PACK = f"""set -u
{AS_ROOT}
held=$($as find . -path ./{KEPT} -prune -o -type f -exec wc -c {{}} + \\
  | awk '!(NF == 2 && $2 == "total") {{ s += $1 }} END {{ printf "%.0f\\n", s }}')
if [ "$held" -gt "$1" ]; then printf '%s\\n' "$held"; exit {PAST}; fi
$as rm -rf ./{KEPT} || exit 70
mkdir -m 700 ./{KEPT} || exit 70
$as tar --numeric-owner --exclude=./{KEPT} -cf - . > ./{PACKED}
code=$?
if [ "$code" -gt 1 ]; then rm -rf ./{KEPT}; exit "$code"; fi
size=$(wc -c < ./{PACKED}) || exit 70
printf '%s\\n' $size
"""
"""The directory measured by the bytes its files hold, `KEPT` aside, and
refused past the bound `$1`; else packed at `PACKED`, and the pack's size.
Tar's exit 1 says a file changed while it was read: the pack holds it as
read."""

UNPACK = f"""set -u
{AS_ROOT}
held=$(find ./{KEPT} -maxdepth 1 -type f -name 'part-*' | wc -l)
if [ "$held" -ne "$1" ]; then exit 65; fi
$as find . -mindepth 1 -maxdepth 1 ! -name {KEPT} -exec rm -rf {{}} + || exit $?
cat ./{KEPT}/part-* | $as tar --numeric-owner -xf - || exit $?
$as rm -rf ./{KEPT}
"""
"""The directory emptied around `KEPT`, then filled from the `$1` parts
written there, in order, and `KEPT` gone."""


def part_path(index: int) -> str:
    """Where a restore writes a part, named so the parts sort in order."""
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
) -> DirectoryPack:
    """The workspace's directory packed at `PACKED`, and measured: nothing of
    it has left the VM yet. One whose files hold more than `bound` bytes is
    refused (`SnapshotRefused`) before it is packed. A pack that fails, or
    takes longer than `within`, is refused; its caller drops what is left."""
    ended = await _run(ctx, transport, record_seal, workspace, PACK, str(bound), epoch, within, now)
    if ended.exit_code == PAST:
        raise SnapshotRefused(
            f"the workspace's directory holds {ended.stdout.strip()} bytes, "
            f"past the bound of {bound}, so no snapshot is kept"
        )
    _completed(ended, "pack", within)
    try:
        size = int(ended.stdout.strip())
    except ValueError as error:
        raise BackendFailed("directory", "pack", f"the pack is not measured: {error}") from error
    return DirectoryPack(location=workspace.location, path=PACKED, size=size)


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
        ctx, transport, record_seal, workspace, f"rm -rf ./{KEPT}", "", epoch, within, now
    )
    _completed(ended, "drop", within)


async def unpack(
    ctx: TenantContext,
    transport: TransportInterface,
    record_seal: RecordSealInterface,
    workspace: AgentWorkspace,
    parts: AsyncIterable[bytes],
    *,
    epoch: int,
    within: timedelta,
    now: datetime,
) -> None:
    """The workspace's directory emptied and filled from the archive whose
    bytes `parts` hold in order: each part written into `KEPT`, then
    unpacked. An error `parts` raises ends it and is raised as it is; what
    it wrote stays for its caller, whose VM goes with it."""
    count = 0
    async for part in parts:
        await transport.write_file(workspace, part_path(count), part, epoch)
        count += 1
    ended = await _run(
        ctx, transport, record_seal, workspace, UNPACK, str(count), epoch, within, now
    )
    _completed(ended, "unpack", within)


async def _run(
    ctx: TenantContext,
    transport: TransportInterface,
    record_seal: RecordSealInterface,
    workspace: AgentWorkspace,
    script: str,
    argument: str,
    epoch: int,
    within: timedelta,
    now: datetime,
) -> CommandResult:
    """One script in the directory under the run's `epoch`, its record
    sealed under the session's key as any command's is."""
    key = new_id()
    command = CommandSpec(
        argv=("sh", "-c", script, "sh", argument),
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
