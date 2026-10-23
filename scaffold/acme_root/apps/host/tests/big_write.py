"""A host that writes one large file into a directory workspace, in a process
of its own, so the memory it reports is the host's alone. Its platform is
faked on the wire: it answers one `write_file` item's detail with the
object and the URL the spec names, renews its lease, and takes its result,
and it records the size of every request the host sends it and when each
renewal lands. Its store is the real one the URL names. It prints, as one
line of JSON, its peak resident memory before and after, those sizes, the
renewals' times, and the result it was pushed.

    python big_write.py '<spec as JSON>'

The spec names `url`, `reference`, `size`, `digest`, `key`, `workspace`,
`home`, and `renew_seconds`."""

import asyncio
import base64
import json
import resource
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from acme.apps.host.ceilings import Ask
from acme.apps.host.exec_relay import EXEC, ExecutorRelayImpl
from acme.client.client import ApiClient
from acme.client.types.hosts import ClaimedWorkView
from acme.client.types.hosts import IsolationMode as HostMode
from acme.infra.agent_workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.local import TransportLocalImpl
from acme.om.base import new_id


def peak() -> int:
    """The most resident memory this process has held, in bytes."""
    most = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return most if sys.platform == "darwin" else most * 1024


async def main(spec: dict[str, Any]) -> dict[str, Any]:
    item_id, org_id, workspace = new_id(), new_id(), str(spec["workspace"])
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


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main(json.loads(sys.argv[1])))))
