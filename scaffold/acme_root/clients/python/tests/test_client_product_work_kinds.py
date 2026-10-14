"""The transport client reads a work item of a kind a product declares,
which the engine's own kinds do not name."""

from uuid import uuid4

import httpx
from test_client import Recorder, client_over


async def test_an_operator_reads_a_work_item_of_a_products_own_kind() -> None:
    org_id, item_id = uuid4(), uuid4()
    item = {
        "id": str(item_id),
        "kind": "RENDER",
        "target_id": str(uuid4()),
        "status": "queued",
        "available_at": "2026-09-18T12:00:00Z",
        "attempts": 0,
        "max_attempts": 5,
        "last_error": None,
        "updated_at": "2026-09-18T12:00:00Z",
    }
    path = f"/v1/admin/orgs/{org_id}/work/{item_id}/requeue"
    recorder = Recorder({path: httpx.Response(200, json=item)})
    async with client_over(recorder) as client:
        requeued = await client.admin_requeue_work(org_id, item_id)
    assert requeued.kind == "RENDER" and requeued.id == item_id
