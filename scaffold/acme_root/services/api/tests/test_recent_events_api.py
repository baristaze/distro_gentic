"""The recent read of the events: newest first from the head, each page
below the last one's oldest down to the floor, and a tenant's own alone."""

from datetime import timedelta

import httpx
from tenant_support import tenant
from test_events_api import REPORT

from acme.om.base import utcnow
from acme.services.api.container import AppContainer


async def test_the_recent_read_opens_at_the_head_and_pages_back_to_the_floor(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    """The newest events come first, each page below the oldest the last one
    held, down to the floor; another tenant's stream never shows, at the head
    or paging back."""
    ajax = []
    for n in range(5):
        made = await client.post(
            "/v1/media/files", headers=owner, json={**REPORT, "name": f"a{n}.pdf"}
        )
        ajax.append(made.json()["id"])
    beta = await tenant(client, container, "beta")
    theirs = set()
    for n in range(7):
        made = await client.post(
            "/v1/media/files", headers=beta.owner, json={**REPORT, "name": f"b{n}.pdf"}
        )
        theirs.add(made.json()["id"])
    # The trim takes the oldest across tenants: Ajax's first two.
    assert (
        await container.storage.get_change_event_storage().trim(utcnow() + timedelta(seconds=1), 2)
        == 2
    )

    async def page(headers: dict[str, str], **params: int) -> list[dict[str, object]]:
        read = await client.get("/v1/events/recent", headers=headers, params={"limit": 2, **params})
        assert read.status_code == 200, read.text
        return read.json()

    head = await page(owner)
    assert [e["seq"] for e in head] == [5, 4]
    assert [e["target_id"] for e in head] == [ajax[4], ajax[3]]
    assert [e["seq"] for e in await page(owner, before_seq=4)] == [3]
    assert await page(owner, before_seq=3) == []
    whole = await page(owner, before_seq=1000, limit=100)
    assert [e["seq"] for e in whole] == [5, 4, 3]
    assert not {e["target_id"] for e in whole} & theirs

    their_head = await page(beta.owner, limit=100)
    assert [e["seq"] for e in their_head] == [7, 6, 5, 4, 3, 2, 1]
    assert {e["target_id"] for e in their_head} == theirs
    assert {e["target_id"] for e in await page(beta.owner, before_seq=4)} <= theirs

    assert (
        await client.get("/v1/events/recent", headers=owner, params={"before_seq": 0})
    ).status_code == 422
    assert (await client.get("/v1/events/recent")).status_code == 401
