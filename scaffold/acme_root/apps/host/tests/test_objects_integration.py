"""A file of a GiB reaches a workspace over the compose stack's store, while
the host that writes it holds no more than 64 MiB beyond what it held
before, sends the platform none of its bytes, and renews its lease on time
throughout. The object is sealed and put in the stack's own bucket by its
parts, a part at a time, under a tenant and a key of the case's own, and
removed afterwards. The host runs in a process of its own (`big_write.py`),
so the memory it reports is its alone."""

import asyncio
import base64
import hashlib
import json
import secrets
import sys
from collections.abc import AsyncIterator
from datetime import timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import aioboto3
import httpx
import pytest

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
from acme.om.base import new_id

pytestmark = pytest.mark.integration

MIB = 1 << 20
GIB = 1 << 30
ROOM = 64 * MIB
"""The most the host's memory may grow while the file moves."""
RENEW = 0.5
"""How often the host renews the item's lease here: a third of the lease."""
ON_TIME = 1.0
"""How late past its schedule a renewal may land."""
API_BYTES = 16 * 1024
"""The most any request to the platform carries: its calls, never the file."""
BUCKET = Buckets.TOOL_OUTPUTS


def endpoint_of_stack() -> str:
    return InfraSettings().s3_endpoint_url or "http://127.0.0.1:59000"


@pytest.fixture
async def store() -> AsyncIterator[BucketsS3Impl]:
    """The S3 impl over the stack's MinIO and its own buckets, signing for
    `localhost` while it talks to `127.0.0.1`."""
    settings = InfraSettings()
    session = aioboto3.Session(
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.aws_region,
    )
    endpoint = endpoint_of_stack()
    impl = BucketsS3Impl(
        session,
        endpoint_url=endpoint,
        region=settings.aws_region,
        bucket_prefix=settings.s3_bucket_prefix,
        timeout=timedelta(seconds=60),
        presign_endpoint_url=endpoint.replace("127.0.0.1", "localhost"),
    )
    await impl.start()
    try:
        yield impl
    finally:
        await impl.close()


async def put_sealed(
    store: BucketsS3Impl, org_id: Any, reference: str, key: bytes, size: int
) -> str:
    """A file of `size` bytes, sealed and sent to the store a part at a
    time, as a host sends one: its digest. Its bytes repeat one random
    frame's, so none of it is held whole here either."""
    frame = secrets.token_bytes(FRAME_PLAIN)
    hasher = hashlib.sha256()
    upload_id = await store.start_upload(org_id, BUCKET, reference, "application/octet-stream")
    async with httpx.AsyncClient(timeout=120) as wire:
        for part in sealed_parts(size):
            frames = []
            for index, last, _, length in frame_slices(size, part.first_frame, part.frames):
                plain = frame[:length]
                hasher.update(plain)
                frames.append(seal_frame(key, reference, index, last, plain))
            body = b"".join(frames)
            url = await store.presign_part(
                org_id,
                BUCKET,
                reference,
                upload_id,
                part.number,
                part.size_bytes,
                timedelta(minutes=15),
            )
            sent = await wire.put(url, content=body)
            assert sent.status_code == 200, sent.text
    await store.complete_upload(org_id, BUCKET, reference, upload_id, sealed_size(size))
    return DIGEST_SCHEME + hasher.hexdigest()


def digest_of_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(8 * MIB):
            hasher.update(chunk)
    return DIGEST_SCHEME + hasher.hexdigest()


# Check 1: a GiB reaches a workspace while the host's memory stays within
# 64 MiB of what it held before, and no request to the API carries its bytes.


async def test_a_gib_reaches_a_workspace_with_the_hosts_memory_within_64_mib_and_its_lease_held(
    store: BucketsS3Impl, tmp_path: Path
) -> None:
    org_id = new_id()
    reference = f"exec_relay/{new_id()}/{new_id()}/1/file"
    key = new_key()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    try:
        digest = await put_sealed(store, org_id, reference, key, GIB)
        url = await store.presign_get(org_id, BUCKET, reference, timedelta(minutes=15))
        spec = {
            "url": url,
            "reference": reference,
            "size": GIB,
            "digest": digest,
            "key": base64.b64encode(key).decode(),
            "workspace": str(workspace),
            "home": str(tmp_path / "home"),
            "renew_seconds": RENEW,
        }
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            str(Path(__file__).with_name("big_write.py")),
            json.dumps(spec),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(child.communicate(), timeout=600)
        assert child.returncode == 0, err.decode()[-2000:]
        report = json.loads(out.decode().strip().splitlines()[-1])
    finally:
        await store.delete(org_id, BUCKET, reference)

    (result,) = report["results"]
    assert result["outcome"]["refused"] is None, result
    grew = report["peak"] - report["before"]
    renewals = [0.0, *report["renewed"], report["took"]]
    late = max(later - earlier for earlier, later in pairwise(renewals))
    print(
        f"moved {GIB // MIB} MiB in {report['took']:.1f}s: the host grew by "
        f"{grew / MIB:.1f} MiB, its largest request to the platform was "
        f"{max(report['sizes'])} bytes, its longest wait between renewals "
        f"{late:.2f}s ({len(report['renewed'])} renewals)"
    )
    assert grew <= ROOM, f"the host's memory grew by {grew // MIB} MiB"
    assert max(report["sizes"]) <= API_BYTES, "no request to the platform carries the file"
    assert late <= RENEW + ON_TIME, f"a renewal came {late:.2f}s after the one before"
    assert report["took"] > 2 * RENEW, "the file took long enough to need renewals"
    written = workspace / "big.bin"
    assert written.stat().st_size == GIB
    assert digest_of_file(written) == digest
    assert list((tmp_path / "home" / "transfers").iterdir()) == []
