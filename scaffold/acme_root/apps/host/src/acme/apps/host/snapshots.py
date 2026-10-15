"""The host's own store of its workspaces' snapshots, inside its owner's wall.
A snapshot's bytes stay here: the platform records the reference the store
knows it by, the SHA-256 of its bytes, and their size, never the bytes.

A snapshot is kept under `<root>/<org_id>/<agent_session_id>/<snapshot_id>`, owner
only, written whole before it is named, so a reader never finds half of
one. One that holds the value of a secret this host keeps for the tenant, in
any form redaction matches, is refused before anything of it is kept: the
host scans it against `values` first. A load
holds the bytes to the digest and the size the platform recorded: bytes gone
or altered are lost, never started from. An erase lets every snapshot of a
session go, when its content goes. Hosts of a pool that share a store's root
reach one another's snapshots; a restore runs on any host whose store holds
the reference.

The store keeps the tenant's workspace bases too, under
`<root>/<org_id>/bases/<key>`, owner only and written whole, as a
snapshot is. A base is the tenant's, not a session's, so no session's
erase reaches it (`acme.apps.host.bases`)."""

import asyncio
import hashlib
import os
import shutil
import stat
from pathlib import Path
from uuid import UUID

DIGEST_SCHEME = "sha256:"

BASES = "bases"
"""The folder of a tenant's bases, beside its sessions' folders, each named
by a session's id, so no session's erase reaches it."""

STORE_FOLDER = "snapshots"


class SnapshotLost(Exception):
    """A snapshot the store was asked for is gone from it, or its bytes do not
    match the digest and the size the platform recorded."""


class SnapshotHeldSecret(Exception):
    """A snapshot holds the value of a secret this host keeps: nothing of it
    is kept. Names the secret, never its value."""


class HostSnapshots:
    """`root` is the store; `secrets` the host's own secret store, keyed by
    tenant first, whose values a snapshot must not hold."""

    def __init__(self, root: Path, secrets: Path) -> None:
        self._root = root
        self._secrets = secrets

    def usable(self) -> bool:
        """Whether the store takes a snapshot and gives it back: the probe a
        host passes before it advertises snapshots."""
        try:
            self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
            probe = self._root / ".probe"
            probe.write_bytes(b"probe")
            kept = probe.read_bytes() == b"probe"
            probe.unlink()
        except OSError:
            return False
        return kept

    async def keep(
        self, org_id: UUID, agent_session_id: UUID, snapshot_id: UUID, archive: bytes
    ) -> tuple[str, str, int]:
        """`archive` kept as the session's snapshot under `snapshot_id`, once
        it is scanned for the host's secrets' values (`values`): the
        reference, the digest, and the size."""
        reference = f"{org_id}/{agent_session_id}/{snapshot_id}"
        await asyncio.to_thread(self._write, reference, archive)
        return reference, DIGEST_SCHEME + hashlib.sha256(archive).hexdigest(), len(archive)

    async def load(self, reference: str, digest: str, size: int) -> bytes:
        """The snapshot's bytes, once they match the digest and the size
        recorded; `SnapshotLost` otherwise."""
        path = self._path(reference)
        try:
            archive = await asyncio.to_thread(path.read_bytes)
        except OSError as error:
            raise SnapshotLost(f"snapshot {reference} is gone from this host's store") from error
        if len(archive) != size or DIGEST_SCHEME + hashlib.sha256(archive).hexdigest() != digest:
            raise SnapshotLost(f"snapshot {reference} does not match the digest it was kept by")
        return archive

    async def keep_base(self, org_id: UUID, key: str, archive: bytes) -> None:
        """`archive` kept as the tenant's base under `key`."""
        await asyncio.to_thread(self._write, f"{org_id}/{BASES}/{key}", archive)

    async def load_base(self, org_id: UUID, key: str) -> bytes | None:
        """The tenant's base under `key`, or None when the store keeps none."""
        path = self._path(f"{org_id}/{BASES}/{key}")
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            return None

    async def drop_base(self, org_id: UUID, key: str) -> None:
        """The tenant's base under `key` goes; one gone already is gone."""
        path = self._path(f"{org_id}/{BASES}/{key}")
        await asyncio.to_thread(path.unlink, True)

    def holds(self, reference: str) -> bool:
        return self._path(reference).is_file()

    async def erase(self, org_id: UUID, agent_session_id: UUID) -> None:
        """Every snapshot of the session goes; one gone already is gone."""
        folder = self._root / str(org_id) / str(agent_session_id)
        await asyncio.to_thread(shutil.rmtree, folder, True)

    def _path(self, reference: str) -> Path:
        parts = reference.split("/")
        if len(parts) != 3 or any(part in {"", ".", ".."} for part in parts):
            raise SnapshotLost(f"{reference!r} names no snapshot of this store")
        return self._root.joinpath(*parts)

    def _write(self, reference: str, archive: bytes) -> None:
        path = self._path(reference)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".partial")
        descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "wb") as out:
            out.write(archive)
            out.flush()
            os.fsync(out.fileno())
        partial.replace(path)

    async def values(self, org_id: UUID) -> dict[str, str]:
        """The values of the secrets this host keeps for the tenant, by name,
        which a snapshot must not hold. `SnapshotHeldSecret` when the store
        is not owner-only."""
        return await asyncio.to_thread(self._values, org_id)

    def _values(self, org_id: UUID) -> dict[str, str]:
        """The `org/<org_id>/<name>=value` lines of its owner-only store."""
        if not self._secrets.exists():
            return {}
        if stat.S_IMODE(self._secrets.stat().st_mode) & 0o077:
            raise SnapshotHeldSecret(f"{self._secrets} is not owner-only, so nothing is kept")
        prefix = f"org/{org_id}/"
        values: dict[str, str] = {}
        for line in self._secrets.read_text().splitlines():
            key, _, value = line.strip().partition("=")
            if key.startswith(prefix) and value.strip():
                values[key.removeprefix(prefix)] = value.strip()
        return values
