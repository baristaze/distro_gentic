"""How a host moves the objects an `exec` item names: a file a write hands
it, a file a read uploads, and what an item printed or listed. Each object
crosses straight between the host and the store, by URLs the platform
signed for it alone, and is sealed under its own key, which the item's
detail hands the host and which opens that object and no other
(`acme.infra.buckets.sealed`).

Each transfer runs on a store client of its own, a connection apart from
the API's, and does its sealing, its hashing, and its disk in a thread, so
the loop that renews the host's leases and beats is never held while a
large object moves. Each spools on the host's disk, in its own folder
(`spool`), so a file of any size holds a few frames of it in memory: a
download is opened frame by frame and hashed as it arrives, and its spool
is used only once it matches the size and the digest the item declares; a
read is spooled from the workspace a chunk at a time and hashed, then
sealed a frame at a time as each part is sent. An upload cut off resumes:
the platform signs only the parts the store does not hold, and those alone
are sent again."""

import asyncio
import base64
import hashlib
import logging
import time
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Literal
from uuid import UUID, uuid4

import httpx

from acme.client.client import ApiClient
from acme.client.transport import WIRE_FAILURES, ApiError
from acme.client.types.exec_relay import IssuedObjectPartView, ObjectRefView, ObjectSlotView
from acme.infra.agent_workspaces import AgentWorkspace
from acme.infra.buckets.sealed import (
    DIGEST_SCHEME,
    ObjectRefused,
    Opener,
    SealedPart,
    frame_slices,
    seal_frame,
    sealed_parts,
)
from acme.infra.transports import TransportInterface
from acme.timing import Retries, RetryPolicy

log = logging.getLogger(__name__)

CHUNK_BYTES = 1024 * 1024
"""What a download is read from the wire in."""
READ_BYTES = 8 * 1024 * 1024
"""What a read spools from the workspace at a time."""
SENDS = 3
"""How many times one part is sent before an upload is given up as one the
store keeps losing."""

ObjectKind = Literal["output", "file"]
ClientFactory = Callable[[], ApiClient]


@dataclass(frozen=True)
class Spooled:
    """A file on the host's disk, its size, and its digest."""

    path: Path
    size: int
    digest: str


class PartRefused(Exception):
    """The store refused a part: its URL ran out, or the store failed."""

    def __init__(self, number: int, status: int) -> None:
        super().__init__(f"the store refused part {number} with {status}")
        self.status = status


class HostObjects:
    """The objects an item moves, spooled under `spool`. `client` calls with
    the host's credential as it is now; a failure the host outlasts is
    waited out after `retry`'s waits, while the item's lease lasts."""

    def __init__(
        self,
        client: ClientFactory,
        spool: Path,
        retry: RetryPolicy,
        jitter: Callable[[], float],
    ) -> None:
        self._client = client
        self._spool = spool
        self._retry = retry
        self._jitter = jitter

    async def _store(self) -> httpx.AsyncClient:
        """A client of the store, on a connection of its own."""
        async with self._client() as client:
            return client.store()

    def _new_spool(self) -> Path:
        self._spool.mkdir(mode=0o700, parents=True, exist_ok=True)
        return self._spool / uuid4().hex

    async def fetch(self, named: ObjectRefView, url: str) -> Spooled:
        """The file a write hands the host, downloaded by `url` into a spool
        and checked: every frame opens under its key at its place, and the
        whole is the size and the digest the item declares. `ObjectRefused`
        otherwise, with nothing of it kept. The caller removes the spool."""
        path = self._new_spool()
        opener = Opener(_key(named.key), named.reference, named.size)
        hasher = hashlib.sha256()
        handle = await asyncio.to_thread(path.open, "wb")
        try:
            store = await self._store()
            async with store, store.stream("GET", url) as answer:
                if answer.is_error:
                    raise ObjectRefused(
                        f"the store refused {named.reference} with {answer.status_code}"
                    )
                async for chunk in answer.aiter_bytes(CHUNK_BYTES):
                    await asyncio.to_thread(_opened, opener, chunk, handle, hasher)
            opener.close()
            await asyncio.to_thread(handle.close)
            digest = DIGEST_SCHEME + hasher.hexdigest()
            if digest != named.digest:
                raise ObjectRefused(f"{named.reference} does not match its digest")
        except BaseException:
            await asyncio.to_thread(handle.close)
            await asyncio.to_thread(path.unlink, True)
            raise
        return Spooled(path, named.size, digest)

    async def spool_read(
        self,
        transport: TransportInterface,
        workspace: AgentWorkspace,
        path: str,
        max_bytes: int,
        offset: int,
    ) -> Spooled:
        """At most `max_bytes` of the file at `path` from `offset`, read
        from the workspace a chunk at a time into a spool, and hashed. The
        caller removes the spool."""
        spool = self._new_spool()
        hasher = hashlib.sha256()
        handle = await asyncio.to_thread(spool.open, "wb")
        total = 0
        try:
            while total < max_bytes:
                asked = min(READ_BYTES, max_bytes - total)
                data = await transport.read_file(workspace, path, asked, offset + total)
                await asyncio.to_thread(_appended, handle, data, hasher)
                total += len(data)
                if len(data) < asked:
                    break
            await asyncio.to_thread(handle.close)
        except BaseException:
            await asyncio.to_thread(handle.close)
            await asyncio.to_thread(spool.unlink, True)
            raise
        return Spooled(spool, total, DIGEST_SCHEME + hasher.hexdigest())

    async def send(
        self,
        item_id: UUID,
        kind: ObjectKind,
        slot: ObjectSlotView,
        source: Spooled | bytes,
        until: float,
    ) -> tuple[int, str]:
        """The object of `kind` sealed from `source` and sent a part at a
        time, each straight to the store by the URL the platform signed for
        it, until the store holds every part: the size and the digest of
        what it sealed. A failure the host outlasts, a part the store
        refused included, is waited out and the parts still missing asked
        for again, so a part the store holds is never sent twice; one that
        would land past `until`, by this host's clock, is raised, as a
        refusal is."""
        if isinstance(source, bytes):
            size, digest = len(source), DIGEST_SCHEME + hashlib.sha256(source).hexdigest()
        else:
            size, digest = source.size, source.digest
        plan = {part.number: part for part in sealed_parts(size)}
        key = _key(slot.key)
        sent: dict[int, int] = {}
        retries = Retries(self._retry, draw=self._jitter)
        async with await self._store() as store:
            while True:
                try:
                    async with self._client() as client:
                        issued = await client.issue_exec_upload(item_id, kind, size)
                    if not issued.parts:
                        return size, digest
                    for part in issued.parts:
                        sent[part.number] = sent.get(part.number, 0) + 1
                        if sent[part.number] > SENDS:
                            raise ObjectRefused(
                                f"the store kept no part {part.number} of {slot.reference}"
                            )
                        planned = plan[part.number]
                        await _put(store, part, planned, key, slot.reference, size, source)
                    retries.reset()
                except (ApiError, PartRefused, *WIRE_FAILURES) as error:
                    if isinstance(error, ApiError) and not _outlasted(error):
                        raise
                    asked = error.retry_after if isinstance(error, ApiError) else None
                    wait = retries.failed(asked)
                    if time.monotonic() + wait >= until:
                        raise
                    log.info("an upload of %s failed (%s); asking again", slot.reference, error)
                    await asyncio.sleep(wait)


def _outlasted(error: ApiError) -> bool:
    return error.status >= 500 or error.status == 429


def _key(text: str) -> bytes:
    return base64.b64decode(text)


def _opened(opener: Opener, chunk: bytes, handle: IO[bytes], hasher: hashlib._Hash) -> None:
    for plain in opener.feed(chunk):
        hasher.update(plain)
        handle.write(plain)


def _appended(handle: IO[bytes], data: bytes, hasher: hashlib._Hash) -> None:
    hasher.update(data)
    handle.write(data)


async def _put(
    store: httpx.AsyncClient,
    part: IssuedObjectPartView,
    planned: SealedPart,
    key: bytes,
    reference: str,
    size: int,
    source: Spooled | bytes,
) -> None:
    """One part, sealed a frame at a time as it is sent: the body of a PUT
    of the length its URL is signed for."""
    if part.size_bytes != planned.size_bytes or part.offset != planned.offset:
        raise ObjectRefused(f"part {part.number} of {reference} is not the one planned")
    body = _sealed(planned, key, reference, size, source)
    try:
        answer = await store.put(
            part.url, content=body, headers={"Content-Length": str(part.size_bytes)}
        )
    finally:
        await body.aclose()
    if answer.is_error:
        raise PartRefused(part.number, answer.status_code)


async def _sealed(
    planned: SealedPart, key: bytes, reference: str, size: int, source: Spooled | bytes
) -> AsyncGenerator[bytes]:
    frames = frame_slices(size, planned.first_frame, planned.frames)
    if isinstance(source, bytes):
        view = memoryview(source)
        for index, last, start, length in frames:
            plain = bytes(view[start : start + length])
            yield await asyncio.to_thread(seal_frame, key, reference, index, last, plain)
        return
    handle = await asyncio.to_thread(source.path.open, "rb")
    try:
        for index, last, start, length in frames:
            yield await asyncio.to_thread(
                _frame, handle, key, reference, index, last, start, length
            )
    finally:
        await asyncio.to_thread(handle.close)


def _frame(
    handle: IO[bytes], key: bytes, reference: str, index: int, last: bool, start: int, length: int
) -> bytes:
    handle.seek(start)
    plain = handle.read(length)
    if len(plain) != length:
        raise ObjectRefused(f"the spool of {reference} ended short of frame {index}")
    return seal_frame(key, reference, index, last, plain)


async def removed(path: Path) -> None:
    """A spool, once its transfer is done with it."""
    await asyncio.to_thread(path.unlink, True)
