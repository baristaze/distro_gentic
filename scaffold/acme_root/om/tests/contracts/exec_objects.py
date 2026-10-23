"""A host's side of the objects an `exec` item moves, in a test: what it
printed and the file it read, sealed and sent straight to the local store
by the parts the relay signs, and the file a write hands it, read back by
the URL its detail carries. Each goes as a host sends it, never through a
service."""

import base64
from collections.abc import Sequence
from uuid import UUID

import httpx

from acme.infra.buckets import BucketsInterface
from acme.infra.buckets.local import BucketsLocalImpl
from acme.infra.buckets.sealed import digest_of, open_object, seal_part, sealed_parts
from acme.infra.transports import FileEntry
from acme.om.base import new_id
from acme.om.context import AppContext, AppType, RequestContext
from acme.om.exec_relay import ExecRelayManagerInterface
from acme.om.exec_relay.types.exec import (
    ExecOutcome,
    ExecResult,
    ObjectKind,
    ObjectSlot,
    Printed,
    StoredObject,
)
from acme.om.hosts.types.host import HostIdentity
from acme.om.retention.crossing import CrossingKind, declared

HOST = AppContext(type=AppType.API, version="host@test")


def _request() -> RequestContext:
    return RequestContext(request_id=new_id(), app=HOST)


def store_of(buckets: BucketsInterface) -> httpx.AsyncClient:
    """A client whose requests reach the local impl's store."""
    assert isinstance(buckets, BucketsLocalImpl), "only the local impl has a store in-process"
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=buckets.store))


def printed(stdout: str = "", stderr: str = "", entries: Sequence[FileEntry] = ()) -> bytes:
    """An output object's bytes, as a host seals them."""
    return Printed(stdout=stdout, stderr=stderr, entries=tuple(entries)).model_dump_json().encode()


async def uploaded(
    relay: ExecRelayManagerInterface,
    buckets: BucketsInterface,
    host: HostIdentity,
    item_id: UUID,
    kind: ObjectKind,
    data: bytes,
) -> StoredObject:
    """`data` uploaded as the item's object of `kind`, every part the relay
    signs sent: what the result names of it."""
    detail = await relay.detail(_request(), host, item_id)
    slot = detail.output if kind == "output" else detail.file_out
    assert slot is not None, f"exec item {item_id} uploads no {kind}"
    await send(relay, buckets, host, item_id, kind, slot, data)
    return StoredObject(size=len(data), digest=digest_of(data))


async def send(
    relay: ExecRelayManagerInterface,
    buckets: BucketsInterface,
    host: HostIdentity,
    item_id: UUID,
    kind: ObjectKind,
    slot: ObjectSlot,
    data: bytes,
    *,
    only: frozenset[int] | None = None,
) -> list[int]:
    """The parts of `data` the store does not hold yet, or those of them
    `only` names, sealed under the slot's key and sent: the numbers sent."""
    plan = {part.number: part for part in sealed_parts(len(data))}
    issued = await relay.issue_upload(_request(), host, item_id, kind, len(data))
    sent: list[int] = []
    async with store_of(buckets) as store:
        for part in issued.parts:
            if only is not None and part.number not in only:
                continue
            body = seal_part(_key(slot.key), slot.reference, data, plan[part.number])
            answer = await store.put(part.url, content=body)
            assert answer.status_code == 200, answer.text
            sent.append(part.number)
    return sent


async def finish(
    relay: ExecRelayManagerInterface,
    buckets: BucketsInterface,
    host: HostIdentity,
    item_id: UUID,
    outcome: ExecOutcome | None = None,
    *,
    stdout: str = "",
    stderr: str = "",
    file: bytes | None = None,
    offset: int = 0,
) -> None:
    """How the item ended, pushed as a host pushes it: its output uploaded
    first when it has one, and a read's file."""
    detail = await relay.detail(_request(), host, item_id)
    output = None
    if detail.output is not None:
        output = await uploaded(relay, buckets, host, item_id, "output", printed(stdout, stderr))
    read = None if file is None else await uploaded(relay, buckets, host, item_id, "file", file)
    result = ExecResult(
        outcome=outcome or ExecOutcome(exit_code=0), output=output, file=read, offset=offset
    )
    data = result.model_dump_json().encode()
    await relay.push_result(_request(), host, item_id, declared(CrossingKind.RESULT, data), data)


async def handed(
    relay: ExecRelayManagerInterface, buckets: BucketsInterface, host: HostIdentity, item_id: UUID
) -> bytes:
    """The file a write hands its host, read by the URL its detail carries
    and opened with the key it hands."""
    detail = await relay.detail(_request(), host, item_id)
    named = detail.file_in
    assert named is not None and detail.url is not None, f"exec item {item_id} writes no file"
    async with store_of(buckets) as store:
        answer = await store.get(detail.url)
    assert answer.status_code == 200, answer.text
    return open_object(_key(named.key), named.reference, named.size, named.digest, answer.content)


def _key(text: str) -> bytes:
    return base64.b64decode(text)
