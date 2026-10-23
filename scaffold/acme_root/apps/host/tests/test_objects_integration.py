"""A file of a GiB reaches a workspace over the compose stack's store, while
the host that writes it holds no more than 64 MiB beyond what it held
before, sends the platform none of its bytes, and renews its lease on time
throughout. The object is sealed and put in the stack's own bucket a part
at a time, under a tenant and a key of the case's own, and removed
afterwards. Each side runs in a process of its own (`big_write.py`), so
the memory the host reports is its alone, and no client the test's process
built before reaches the store."""

import asyncio
import hashlib
import json
import sys
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from acme.infra.buckets.sealed import DIGEST_SCHEME
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
SIDE = Path(__file__).with_name("big_write.py")


async def side(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    """One side of the write, in a process of its own: what it printed."""
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        str(SIDE),
        name,
        json.dumps(spec),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(child.communicate(), timeout=600)
    assert child.returncode == 0, err.decode()[-2000:]
    return json.loads(out.decode().strip().splitlines()[-1])


def digest_of_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(8 * MIB):
            hasher.update(chunk)
    return DIGEST_SCHEME + hasher.hexdigest()


# Check 1: a GiB reaches a workspace while the host's memory stays within
# 64 MiB of what it held before, and no request to the API carries its bytes.


async def test_a_gib_reaches_a_workspace_with_the_hosts_memory_within_64_mib_and_its_lease_held(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    spec: dict[str, Any] = {
        "org_id": str(new_id()),
        "reference": f"exec_relay/{new_id()}/{new_id()}/1/file",
        "size": GIB,
        "workspace": str(workspace),
        "home": str(tmp_path / "home"),
        "renew_seconds": RENEW,
    }
    try:
        spec |= await side("put", spec)
        report = await side("host", spec)
    finally:
        await side("delete", spec)

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
    assert digest_of_file(written) == spec["digest"]
    assert list((tmp_path / "home" / "transfers").iterdir()) == []
