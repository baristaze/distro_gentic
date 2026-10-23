"""The two sides of a large write over the compose stack's store, each in a
process of its own, so neither shares the test's process and the memory
the host reports is the host's alone. Each prints one line of JSON.

    python big_write.py put '<spec>'     # the platform's side
    python big_write.py host '<spec>'    # the host's side
    python big_write.py delete '<spec>'

`put` seals a file of `size` bytes, whose bytes repeat one random frame's,
and sends it to the store's own `tool-outputs` bucket a part at a time
under the tenant and the reference the spec names, as a host sends one;
it prints its digest, its key, and a URL signed for a GET of it. `host`
runs a host that writes that file into a directory workspace: its platform
is faked on the wire, answering one `write_file` item's detail with the
object and the URL, renewing its lease, and taking its result, and it
records the size of every request the host sends it and when each renewal
lands. It prints its peak resident memory before and after the write,
those sizes, the renewals' times, and the result it was pushed. `delete`
removes the object."""

import asyncio
import base64
import hashlib
import json
import resource
import secrets
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import aioboto3
import httpx

from acme.apps.host.ceilings import Ask
from acme.apps.host.exec_relay import EXEC, ExecutorRelayImpl
from acme.client.client import ApiClient
from acme.client.types.hosts import ClaimedWorkView
from acme.client.types.hosts import IsolationMode as HostMode
from acme.infra.agent_workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.infra.buckets import Buckets
from acme.infra.buckets.s3 import BucketsS3Impl
from acme.infra.buckets.sealed import (
    DIGEST_SCHEME,
    FRAME_PLAIN,
    frame_slices,
    new_key,
    seal_frame,
    sealed_parts,
    sealed_size,
)
from acme.infra.impl.settings import InfraSettings
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.local import TransportLocalImpl
from acme.om.base import new_id

BUCKET = Buckets.TOOL_OUTPUTS


def peak() -> int:
    """The most resident memory this process has held, in bytes."""
    most = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return most if sys.platform == "darwin" else most * 1024


def store() -> BucketsS3Impl:
    """The stack's MinIO and its own buckets, signing for `localhost` while
    talking to `127.0.0.1`."""
    settings = InfraSettings()
    endpoint = settings.s3_endpoint_url or "http://127.0.0.1:59000"
    return BucketsS3Impl(
        aioboto3.Session(
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.aws_region,
        ),
        endpoint_url=endpoint,
        region=settings.aws_region,
        bucket_prefix=settings.s3_bucket_prefix,
        timeout=timedelta(seconds=60),
        presign_endpoint_url=endpoint.replace("127.0.0.1", "localhost"),
    )


async def put(spec: dict[str, Any]) -> dict[str, Any]:
    org_id, reference, size = UUID(spec["org_id"]), spec["reference"], int(spec["size"])
    key = new_key()
    frame = secrets.token_bytes(FRAME_PLAIN)
    hasher = hashlib.sha256()
    buckets = store()
    await buckets.start()
    try:
        upload_id = await buckets.start_upload(
            org_id, BUCKET, reference, "application/octet-stream"
        )
        async with httpx.AsyncClient(timeout=120) as wire:
            for part in sealed_parts(size):
                frames = []
                for index, last, _, length in frame_slices(size, part.first_frame, part.frames):
                    plain = frame[:length]
                    hasher.update(plain)
                    frames.append(seal_frame(key, reference, index, last, plain))
                url = await buckets.presign_part(
                    org_id,
                    BUCKET,
                    reference,
                    upload_id,
                    part.number,
                    part.size_bytes,
                    timedelta(minutes=15),
                )
                sent = await wire.put(url, content=b"".join(frames))
                sent.raise_for_status()
        await buckets.complete_upload(org_id, BUCKET, reference, upload_id, sealed_size(size))
        url = await buckets.presign_get(org_id, BUCKET, reference, timedelta(minutes=15))
    finally:
        await buckets.close()
    return {
        "digest": DIGEST_SCHEME + hasher.hexdigest(),
        "key": base64.b64encode(key).decode(),
        "url": url,
    }


async def delete(spec: dict[str, Any]) -> dict[str, Any]:
    buckets = store()
    await buckets.start()
    try:
        await buckets.delete(UUID(spec["org_id"]), BUCKET, spec["reference"])
    finally:
        await buckets.close()
    return {"deleted": spec["reference"]}


async def host(spec: dict[str, Any]) -> dict[str, Any]:
    item_id, org_id, workspace = new_id(), UUID(spec["org_id"]), str(spec["workspace"])
    sizes: list[int] = []
    renewed: list[float] = []
    results: list[dict[str, Any]] = []
    detail = {
        "agent_session_id": str(new_id()),
        "call_id": str(new_id()),
        "deadline": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        "effect": "idempotent",
        "epoch": 1,
        "item_id": str(item_id),
        "location": workspace,
        "org_id": str(org_id),
        "request": {"operation": "write_file", "path": "big.bin"},
        "spec": IsolationSpec(
            mode=IsolationMode.HOST, egress=EgressPolicy(mode=EgressMode.NONE)
        ).model_dump(mode="json"),
        "file_in": {
            "reference": spec["reference"],
            "size": spec["size"],
            "digest": spec["digest"],
            "key": spec["key"],
        },
        "url": spec["url"],
    }

    def answer(request: httpx.Request) -> httpx.Response:
        sizes.append(len(request.content))
        call = request.url.path.removeprefix(f"/v1/hosts/me/exec/{item_id}").strip("/")
        if not call:
            return httpx.Response(200, json=detail)
        if call == "lease":
            renewed.append(time.monotonic())
            return httpx.Response(200, json={"lease_expires_at": datetime.now(UTC).isoformat()})
        if call == "result":
            results.append(json.loads(base64.b64decode(json.loads(request.content)["data"])))
        return httpx.Response(204)

    def client() -> ApiClient:
        return ApiClient(
            "http://platform.test",
            app="api",
            app_version="host@test",
            token="host",
            transport=httpx.MockTransport(answer),
        )

    home = Path(spec["home"])
    executor = ExecutorRelayImpl(
        client,
        {
            IsolationMode.HOST: TransportLocalImpl(
                home / "records", SecretsLocalImpl(None), BrokerNullImpl()
            )
        },
        spool=home / "transfers",
        renew_seconds=float(spec["renew_seconds"]),
    )
    item = ClaimedWorkView(
        attempts=1,
        id=new_id(),
        kind=EXEC,
        lease_expires_at=None,
        org_id=org_id,
        payload={"item_id": str(item_id)},
        target_id=item_id,
        wire_version=2,
    )
    ask = Ask(
        kind=EXEC,
        operation=None,
        agent_project_id=None,
        isolation=HostMode.directory,
        egress=frozenset(),
        reads=(workspace,),
        by_person=False,
    )
    before = peak()
    began = time.monotonic()
    await executor.run(item, ask)
    ended = time.monotonic()
    return {
        "before": before,
        "peak": peak(),
        "sizes": sizes,
        "renewed": [at - began for at in renewed],
        "took": ended - began,
        "results": results,
    }


SIDES = {"put": put, "host": host, "delete": delete}

if __name__ == "__main__":
    print(json.dumps(asyncio.run(SIDES[sys.argv[1]](json.loads(sys.argv[2])))))
