"""A host's side of an `exec` item over the wire, in a test or a check: what
the item printed, sealed under the key its detail hands and sent straight
to the store by the parts the platform signs, then the result that names
it by its size and its digest. Nothing of the output crosses the API."""

import base64
import hashlib
from collections.abc import Mapping

import httpx

from acme.infra.buckets import BucketsInterface
from acme.infra.buckets.local import BucketsLocalImpl
from acme.infra.buckets.sealed import digest_of, seal_part, sealed_parts
from acme.om.exec_relay.types.exec import ExecOutcome, ExecResult, Printed, StoredObject


def store_for(buckets: BucketsInterface) -> httpx.AsyncClient:
    """A client of the store a URL the platform signed names: the local
    impl's, in-process, or the network's."""
    if isinstance(buckets, BucketsLocalImpl):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=buckets.store))
    return httpx.AsyncClient()


async def settle_exec(
    client: httpx.AsyncClient,
    headers: Mapping[str, str],
    item_id: str,
    store: httpx.AsyncClient,
    *,
    exit_code: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> httpx.Response:
    """How the item ended, settled as a host settles it; the answer to the
    push of its result."""
    held = await client.get(f"/v1/hosts/me/exec/{item_id}", headers=dict(headers))
    held.raise_for_status()
    slot = held.json()["output"]
    data = Printed(stdout=stdout, stderr=stderr).model_dump_json().encode()
    issued = await client.post(
        f"/v1/hosts/me/exec/{item_id}/upload",
        headers=dict(headers),
        json={"object": "output", "size_bytes": len(data)},
    )
    issued.raise_for_status()
    plan = {part.number: part for part in sealed_parts(len(data))}
    key = base64.b64decode(slot["key"])
    for part in issued.json()["parts"]:
        body = seal_part(key, slot["reference"], data, plan[part["number"]])
        put = await store.put(part["url"], content=body)
        put.raise_for_status()
    result = ExecResult(
        outcome=ExecOutcome(exit_code=exit_code),
        output=StoredObject(size=len(data), digest=digest_of(data)),
    )
    raw = result.model_dump_json().encode()
    return await client.post(
        f"/v1/hosts/me/exec/{item_id}/result",
        headers=dict(headers),
        json={
            "data": base64.b64encode(raw).decode(),
            "crossing": {
                "kind": "result",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
            },
        },
    )
