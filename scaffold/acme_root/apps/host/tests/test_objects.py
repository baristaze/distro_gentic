"""A host moves the objects an `exec` item names straight to and from the
store, by the URLs the platform signed for them alone. An upload cut off
partway is asked for again and sends only the parts the store does not
hold, within the item's lease as it was last renewed; one whose part the
store keeps refusing ends in a refusal the host pushes. A write's file
reaches the workspace only once it opens under its key and matches the
size and the digest its item declares: one that does not, or one whose
URL ran out or names another object, is refused, and nothing of it is
written. No API request carries a file's bytes.

The platform is faked on the wire; the store is the local impl's, served
in-process; the host's executor and its directory transport are the ones
a host runs."""

import asyncio
import base64
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from acme.apps.host.ceilings import Ask
from acme.apps.host.exec_relay import EXEC, ExecutorRelayImpl
from acme.client.client import ApiClient
from acme.client.types.hosts import ClaimedWorkView
from acme.client.types.hosts import IsolationMode as HostMode
from acme.infra.agent_workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.infra.buckets import Buckets
from acme.infra.buckets.local import BucketsLocalImpl
from acme.infra.buckets.sealed import (
    digest_of,
    new_key,
    open_object,
    seal_object,
    sealed_parts,
    sealed_size,
)
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.local import TransportLocalImpl
from acme.om.base import new_id

BUCKET = Buckets.TOOL_OUTPUTS
DIRECTORY = IsolationSpec(mode=IsolationMode.HOST, egress=EgressPolicy(mode=EgressMode.NONE))
MIB = 1 << 20
BIG = 20 * MIB + 12_345
"""A file of three parts: two whole, and the rest."""


def b64(key: bytes) -> str:
    return base64.b64encode(key).decode()


@dataclass
class Platform:
    """The platform's side of the wire for one item, recorded: its detail,
    the parts of an upload it signs from the store's own list, and the
    result it is pushed. It records the size of every request the host
    sends it."""

    buckets: BucketsLocalImpl
    org_id: UUID
    detail: dict[str, Any]
    slots: dict[str, dict[str, str]] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)
    sizes: list[int] = field(default_factory=list)
    issued: list[list[int]] = field(default_factory=list)
    renewed: int = 0

    def client(self, store: httpx.AsyncBaseTransport) -> Callable[[], ApiClient]:
        def built() -> ApiClient:
            return ApiClient(
                "http://platform.test",
                app="api",
                app_version="test",
                token="host",
                transport=httpx.MockTransport(self._answer),
                store_transport=store,
            )

        return built

    async def _answer(self, request: httpx.Request) -> httpx.Response:
        self.sizes.append(len(request.content))
        _, _, call = request.url.path.removeprefix("/v1/hosts/me/exec/").partition("/")
        if not call:
            return httpx.Response(200, json=self.detail)
        if call == "lease":
            self.renewed += 1
            return httpx.Response(200, json={"lease_expires_at": datetime.now(UTC).isoformat()})
        if call == "upload":
            asked = json.loads(request.content)
            slot = self.slots[asked["object"]]
            plan = sealed_parts(asked["size_bytes"])
            held = await self.buckets.list_parts(
                self.org_id, BUCKET, slot["reference"], slot["upload_id"], len(plan)
            )
            have = {part.number: part.size_bytes for part in held}
            missing = [part for part in plan if have.get(part.number) != part.size_bytes]
            self.issued.append([part.number for part in missing])
            parts = [
                {
                    "number": part.number,
                    "offset": part.offset,
                    "size_bytes": part.size_bytes,
                    "url": await self.buckets.presign_part(
                        self.org_id,
                        BUCKET,
                        slot["reference"],
                        slot["upload_id"],
                        part.number,
                        part.size_bytes,
                        timedelta(minutes=5),
                    ),
                }
                for part in missing
            ]
            expires = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
            return httpx.Response(
                200, json={"parts": parts, "remaining": len(missing), "expires_at": expires}
            )
        if call == "result":
            data = json.loads(request.content)["data"]
            self.results.append(json.loads(base64.b64decode(data)))
            return httpx.Response(204)
        return httpx.Response(204)  # parts


class Store(httpx.AsyncBaseTransport):
    """The local store, in-process, recording each part a PUT sends by its
    number and when, by this host's clock. It fails the first PUT of each
    number in `drops` on the wire, as a connection cut partway does, answers
    every PUT of a number in `refuses` with a 503, and takes `slow` seconds
    over each part it holds, as a slow link does."""

    def __init__(
        self,
        buckets: BucketsLocalImpl,
        drops: frozenset[int] = frozenset(),
        *,
        refuses: frozenset[int] = frozenset(),
        slow: float = 0.0,
    ) -> None:
        self._inner = httpx.ASGITransport(app=buckets.store)
        self._drops = set(drops)
        self._refuses = refuses
        self._slow = slow
        self.put: list[int] = []
        self.at: list[float] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            number = int(request.url.params["partNumber"])
            self.put.append(number)
            self.at.append(time.monotonic())
            if number in self._drops:
                self._drops.discard(number)
                raise httpx.WriteError("the connection was cut", request=request)
            if number in self._refuses:
                return httpx.Response(503, text="the store is busy")
            await asyncio.sleep(self._slow)
        return await self._inner.handle_async_request(request)


def claimed() -> ClaimedWorkView:
    item_id = new_id()
    return ClaimedWorkView(
        attempts=1,
        id=new_id(),
        kind=EXEC,
        lease_expires_at=None,
        org_id=new_id(),
        payload={"item_id": str(item_id)},
        target_id=item_id,
        wire_version=2,
    )


def asked(where: Path) -> Ask:
    return Ask(
        kind=EXEC,
        operation=None,
        agent_project_id=None,
        isolation=HostMode.directory,
        egress=frozenset(),
        reads=(str(where),),
        by_person=False,
    )


def detail_of(item: ClaimedWorkView, where: Path, request: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_session_id": str(new_id()),
        "call_id": str(new_id()),
        "deadline": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        "effect": "idempotent",
        "epoch": 1,
        "item_id": str(item.target_id),
        "location": str(where),
        "org_id": str(item.org_id),
        "request": request,
        "spec": DIRECTORY.model_dump(mode="json"),
    }


def executor_of(
    platform: Platform, store: httpx.AsyncBaseTransport, tmp_path: Path
) -> ExecutorRelayImpl:
    transport = TransportLocalImpl(tmp_path / "records", SecretsLocalImpl(None), BrokerNullImpl())
    return ExecutorRelayImpl(
        platform.client(store),
        {IsolationMode.HOST: transport},
        spool=tmp_path / "transfers",
        renew_seconds=0.2,
    )


@pytest.fixture
def where(tmp_path: Path) -> Path:
    folder = tmp_path / "workspace"
    folder.mkdir()
    return folder


@pytest.fixture
def buckets(tmp_path: Path) -> BucketsLocalImpl:
    return BucketsLocalImpl(tmp_path / "buckets")


@dataclass(frozen=True)
class Read:
    """A read of `out.bin` whose file its host uploads: the item, the
    platform's side of it, and the upload its file lands by."""

    item: ClaimedWorkView
    platform: Platform
    data: bytes
    reference: str
    key: bytes
    upload_id: str


async def read_of(where: Path, buckets: BucketsLocalImpl) -> Read:
    data = bytes(range(256)) * (BIG // 256) + b"tail"
    (where / "out.bin").write_bytes(data)
    item = claimed()
    reference = f"exec_relay/{new_id()}/{item.target_id}/1/file"
    key = new_key()
    upload_id = await buckets.start_upload(
        item.org_id, BUCKET, reference, "application/octet-stream"
    )
    request = {"operation": "read_file", "path": "out.bin", "max_bytes": 64 * MIB}
    platform = Platform(buckets, item.org_id, detail_of(item, where, request))
    platform.detail["file_out"] = {"reference": reference, "key": b64(key)}
    platform.slots["file"] = {"reference": reference, "key": b64(key), "upload_id": upload_id}
    return Read(item, platform, data, reference, key, upload_id)


async def held_whole(buckets: BucketsLocalImpl, read: Read) -> bytes:
    """The read's file as the store holds it once its upload completes."""
    org_id, reference = read.item.org_id, read.reference
    size = sealed_size(len(read.data))
    await buckets.complete_upload(org_id, BUCKET, reference, read.upload_id, size)
    held = await buckets.get(org_id, BUCKET, reference)
    return open_object(read.key, reference, len(read.data), digest_of(read.data), held)


# Check 2: an upload cut off partway resumes and sends only the missing parts.


async def test_an_upload_cut_off_partway_resumes_and_sends_only_the_missing_parts(
    tmp_path: Path, where: Path, buckets: BucketsLocalImpl
) -> None:
    read = await read_of(where, buckets)
    item, platform, data = read.item, read.platform, read.data
    store = Store(buckets, drops=frozenset({2}))
    # A spool a host left as it stopped mid-transfer goes as the next starts.
    (tmp_path / "transfers").mkdir()
    (tmp_path / "transfers" / "left").write_bytes(b"what a crash cut")

    await executor_of(platform, store, tmp_path).run(item, asked(where))

    (result,) = platform.results
    assert result["outcome"]["refused"] is None, result
    assert result["file"] == {"size": len(data), "digest": digest_of(data)}
    assert len(sealed_parts(len(data))) == 3
    assert store.put == [1, 2, 2, 3], "part 2 again after the cut, part 1 never again"
    assert platform.issued == [[1, 2, 3], [2, 3], []], "each ask signs only what is missing"
    assert await held_whole(buckets, read) == data
    assert max(platform.sizes) < 4096, "no request to the platform carries the file's bytes"
    assert list((tmp_path / "transfers").iterdir()) == [], "the spool goes once it is sent"


# Check 8: an upload that outlasts its item's first lease resumes after a
# cut part, and a part the store keeps refusing ends the item with a refusal
# its host pushes, never with its lease running out.

LEASE = 3 * 0.2
"""The lease a renewal holds, at the executor's `renew_seconds`."""


async def test_an_upload_that_outlasts_its_first_lease_resumes_after_a_cut_part(
    tmp_path: Path, where: Path, buckets: BucketsLocalImpl
) -> None:
    read = await read_of(where, buckets)
    platform, data = read.platform, read.data
    store = Store(buckets, drops=frozenset({3}), slow=0.4)
    claimed_at = time.monotonic()

    await executor_of(platform, store, tmp_path).run(read.item, asked(where))

    assert store.put == [1, 2, 3, 3], "part 3 again after the cut, the others never"
    assert store.at[2] - claimed_at > LEASE, "the part was cut past the item's first lease"
    assert platform.renewed >= 2, "its lease was renewed while it uploaded"
    (result,) = platform.results
    assert result["outcome"]["refused"] is None, result
    assert result["file"] == {"size": len(data), "digest": digest_of(data)}
    assert await held_whole(buckets, read) == data


async def test_a_part_the_store_keeps_refusing_ends_the_item_with_a_refusal_its_host_pushes(
    tmp_path: Path, where: Path, buckets: BucketsLocalImpl
) -> None:
    read = await read_of(where, buckets)
    platform = read.platform
    store = Store(buckets, refuses=frozenset({3}), slow=0.4)
    claimed_at = time.monotonic()

    await executor_of(platform, store, tmp_path).run(read.item, asked(where))

    assert store.put == [1, 2, 3, 3, 3], "a refused part is sent again, a bounded few times"
    assert store.at[2] - claimed_at > LEASE, "the store refused it past the item's first lease"
    (result,) = platform.results
    assert result["outcome"]["refused"] == "object_not_sent", result
    assert "the store kept no part 3" in result["detail"]
    assert list((tmp_path / "transfers").iterdir()) == [], "the spool goes all the same"


# Check 5: a file whose digest or size does not match is refused, and
# nothing of it is written into the workspace. Check 3, on the host's side:
# a URL that ran out, or one that names another object, reads nothing.


async def handed(
    tmp_path: Path,
    where: Path,
    buckets: BucketsLocalImpl,
    data: bytes,
    *,
    size: int | None = None,
    digest: str | None = None,
    stored: bytes | None = None,
    ttl: timedelta = timedelta(minutes=5),
    elsewhere: tuple[UUID, str] | None = None,
) -> dict[str, Any]:
    """A write of `data` to `in.bin`, its object put sealed in the store, and
    its detail declaring `size` and `digest` (the file's own unless named),
    with a URL good for `ttl` signed for its own object, or for the one
    `elsewhere` names, a tenant's and its place. What the host pushed."""
    item = claimed()
    reference = f"exec_relay/{new_id()}/{item.target_id}/1/file"
    key = new_key()
    sealed = seal_object(key, reference, data) if stored is None else stored
    await buckets.put(item.org_id, BUCKET, reference, sealed, "application/octet-stream")
    signed_for = elsewhere or (item.org_id, reference)
    url = await buckets.presign_get(signed_for[0], BUCKET, signed_for[1], ttl)
    platform = Platform(
        buckets,
        item.org_id,
        detail_of(item, where, {"operation": "write_file", "path": "in.bin"}),
    )
    platform.detail["file_in"] = {
        "reference": reference,
        "size": len(data) if size is None else size,
        "digest": digest or digest_of(data),
        "key": b64(key),
    }
    platform.detail["url"] = url
    await executor_of(platform, Store(buckets), tmp_path).run(item, asked(where))
    (result,) = platform.results
    assert max(platform.sizes) < 4096, "no request to the platform carries the file's bytes"
    return result


async def test_a_file_that_matches_its_digest_and_its_size_reaches_the_workspace(
    tmp_path: Path, where: Path, buckets: BucketsLocalImpl
) -> None:
    data = bytes(range(256)) * (3 * MIB // 256)
    result = await handed(tmp_path, where, buckets, data)
    assert result["outcome"]["refused"] is None, result
    assert (where / "in.bin").read_bytes() == data
    assert list((tmp_path / "transfers").iterdir()) == [], "the spool goes once it is written"


async def test_a_file_whose_digest_or_size_does_not_match_is_refused_and_nothing_is_written(
    tmp_path: Path, where: Path, buckets: BucketsLocalImpl
) -> None:
    data = bytes(range(256)) * (2 * MIB // 256) + b"rest"
    other_key = new_key()
    cases = {
        "a digest it does not match": {"digest": digest_of(b"another file")},
        "a size short of its bytes": {"size": len(data) - 1},
        "a size past its bytes": {"size": len(data) + 1},
        "bytes altered in the store": {
            "stored": seal_object(other_key, "elsewhere", data),
        },
    }
    for case, declared in cases.items():
        result = await handed(tmp_path, where, buckets, data, **declared)
        assert result["outcome"]["refused"] == "object_refused", (case, result)
        assert not (where / "in.bin").exists(), case
        assert list((tmp_path / "transfers").iterdir()) == [], case


async def test_a_url_that_ran_out_or_names_another_object_reads_nothing(
    tmp_path: Path, where: Path, buckets: BucketsLocalImpl
) -> None:
    data = b"the file\n" * 1000
    expired = await handed(tmp_path, where, buckets, data, ttl=timedelta(seconds=-1))
    assert expired["outcome"]["refused"] == "object_refused", expired
    assert "403" in expired["detail"]
    org_id = new_id()
    other = "exec_relay/another/item/1/file"
    await buckets.put(org_id, BUCKET, other, seal_object(new_key(), other, data), "x")
    another = await handed(tmp_path, where, buckets, data, elsewhere=(org_id, other))
    assert another["outcome"]["refused"] == "object_refused", another
    assert not (where / "in.bin").exists()
    # A URL signed for one object, its path pointed at another, is refused.
    url = await buckets.presign_get(org_id, BUCKET, other, timedelta(minutes=5))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=buckets.store)) as store:
        assert (await store.get(url)).status_code == 200
        moved = await store.get(url.replace("/another/", "/anyone/"))
    assert moved.status_code == 403 and moved.text == "the signature does not match"
