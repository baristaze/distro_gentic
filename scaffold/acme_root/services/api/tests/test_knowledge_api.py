"""A tenant's knowledge over the API: a person writes an entry, reads it and
the entries in a state, edits it on the version they read, and keeps or
rejects an agent's suggestion. A viewer reads and writes none; another
tenant's entry is not found; a malformed entry is refused whole."""

from uuid import UUID

import httpx
from tenant_support import person, refused, tenant

from acme.om.base import new_id, utcnow
from acme.om.context import Role
from acme.om.knowledge.types.knowledge import Knowledge
from acme.services.api.container import AppContainer

ENTRY = {
    "title": "the staging database",
    "trigger": ["staging", "database"],
    "text": "Staging resets nightly; seed it before a run.",
}


async def suggested(container: AppContainer, org_id: UUID) -> UUID:
    """An agent's suggestion, as its session would leave it."""
    now, session = utcnow(), new_id()
    entry = Knowledge(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=session,
        updated_by=session,
        title="the export",
        trigger=("export",),
        text="The export times out past a thousand rows.",
        suggested_by=session,
    )
    await container.storage.get_knowledge_storage().create_entry(org_id, entry, ())
    return entry.id


async def test_a_person_writes_reads_lists_and_edits_an_entry(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    member = await person(client, container, ajax.org_id, Role.MEMBER)
    keyed = {**member, "Idempotency-Key": "write-the-staging-entry"}
    written = await client.post("/v1/knowledge", headers=keyed, json=ENTRY)
    assert written.status_code == 201, written.text
    entry = written.json()
    retried = await client.post("/v1/knowledge", headers=keyed, json=ENTRY)
    assert retried.json() == entry
    assert entry["status"] == "reviewed"
    assert entry["version"] == 1
    url = f"/v1/knowledge/{entry['id']}"
    assert (await client.get(url, headers=ajax.owner)).json() == entry
    listed = await client.get("/v1/knowledge", headers=ajax.owner)
    assert [e["id"] for e in listed.json()] == [entry["id"]]
    edit = {**ENTRY, "text": "Staging resets at two; seed it first."}
    edited = await client.put(url, headers=at(ajax.owner, 1), json=edit)
    assert edited.status_code == 200, edited.text
    assert edited.json()["text"] == edit["text"]
    assert edited.json()["version"] == 2
    assert edited.json()["status"] == "reviewed"
    assert edited.json()["reviewed_by"] != entry["reviewed_by"]
    stale = await client.put(url, headers=at(member, 1), json=ENTRY)
    refused(stale, 412, "precondition_failed")
    refused(await client.put(url, headers=member, json=ENTRY), 422, "validation_failed")


async def test_a_person_keeps_or_rejects_a_suggestion(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    kept, rejected = (
        await suggested(container, ajax.org_id),
        await suggested(container, ajax.org_id),
    )
    waiting = await client.get("/v1/knowledge", headers=ajax.owner, params={"status": "suggested"})
    assert {e["id"] for e in waiting.json()} == {str(kept), str(rejected)}
    keep = await client.post(
        f"/v1/knowledge/{kept}/review", headers=ajax.owner, json={"keep": True}
    )
    assert keep.status_code == 200, keep.text
    assert keep.json()["status"] == "reviewed"
    drop = await client.post(
        f"/v1/knowledge/{rejected}/review", headers=ajax.owner, json={"keep": False}
    )
    assert drop.json()["status"] == "rejected"
    again = await client.post(
        f"/v1/knowledge/{kept}/review", headers=ajax.owner, json={"keep": False}
    )
    refused(again, 409, "conflict")
    edit = await client.put(f"/v1/knowledge/{rejected}", headers=at(ajax.owner, 2), json=ENTRY)
    refused(edit, 409, "conflict")


async def test_a_viewer_reads_knowledge_and_writes_none(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    viewer = await person(client, container, ajax.org_id, Role.VIEWER)
    waiting = await suggested(container, ajax.org_id)
    url = f"/v1/knowledge/{waiting}"
    assert (await client.get(url, headers=viewer)).status_code == 200
    writes = [
        await client.post("/v1/knowledge", headers=viewer, json=ENTRY),
        await client.put(url, headers=at(viewer, 1), json=ENTRY),
        await client.post(f"{url}/review", headers=viewer, json={"keep": True}),
    ]
    for response in writes:
        refused(response, 403, "not_authorized")
    assert (await client.get(url, headers=viewer)).json()["status"] == "suggested"


async def test_another_tenants_entry_is_not_found_and_left_as_it_is(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    bravo = await tenant(client, container, "bravo")
    waiting = await suggested(container, ajax.org_id)
    url = f"/v1/knowledge/{waiting}"
    crossings = [
        await client.get(url, headers=bravo.owner),
        await client.put(url, headers=at(bravo.owner, 1), json=ENTRY),
        await client.post(f"{url}/review", headers=bravo.owner, json={"keep": True}),
    ]
    for response in crossings:
        refused(response, 404, "not_found")
    listed = await client.get("/v1/knowledge", headers=bravo.owner, params={"status": "suggested"})
    assert listed.json() == []
    assert (await client.get(url, headers=ajax.owner)).json()["status"] == "suggested"


async def test_a_malformed_entry_is_refused_whole(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    bad = [
        {**ENTRY, "title": ""},
        {**ENTRY, "trigger": []},
        {**ENTRY, "trigger": ["w"] * 21},
        {**ENTRY, "text": "x" * 10_001},
        {**ENTRY, "status": "reviewed"},
    ]
    for body in bad:
        response = await client.post("/v1/knowledge", headers=ajax.owner, json=body)
        refused(response, 422, "validation_failed")
    status = await client.get("/v1/knowledge", headers=ajax.owner, params={"status": "any"})
    refused(status, 422, "validation_failed")
    assert (await client.get("/v1/knowledge", headers=ajax.owner)).json() == []


def at(headers: dict[str, str], version: int) -> dict[str, str]:
    """The headers with `If-Match` naming the version read."""
    return {**headers, "If-Match": f'"{version}"'}
