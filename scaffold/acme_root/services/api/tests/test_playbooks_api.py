"""A tenant's playbooks over the API: a person publishes a name's next
version with its gates, and the latest version is read, each with what the
lever checks found in it, which never refuses the publish, and null on a
version the checks never read. A viewer publishes none; another tenant's
playbook is not found; a malformed draft, a gate that would allow among
them, is refused whole."""

import httpx
from tenant_support import person, refused, tenant

from acme.om.base import new_id, utcnow
from acme.om.context import Role
from acme.om.playbooks.types.playbook import Playbook
from acme.services.api.container import AppContainer

DRAFT = {
    "name": "release-check",
    "description": "What a release needs before it ships.",
    "body": "1. Run the checks.\n2. Read the diff.\n3. Never push to main.",
    "gates": [{"tool": "git_push", "decision": "approve"}],
}


async def test_a_person_publishes_versions_and_the_latest_is_read(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    member = await person(client, container, ajax.org_id, Role.MEMBER)
    keyed = {**member, "Idempotency-Key": "publish-release-check"}
    first = await client.post("/v1/playbooks", headers=keyed, json=DRAFT)
    assert first.status_code == 201, first.text
    assert first.json()["version"] == 1
    assert (await client.post("/v1/playbooks", headers=keyed, json=DRAFT)).json() == first.json()
    assert first.json()["gates"] == [
        {"tool": "git_push", "authorization_class": None, "decision": "approve"}
    ]
    second = await client.post(
        "/v1/playbooks", headers=ajax.owner, json={**DRAFT, "body": "Run the checks."}
    )
    assert second.json()["version"] == 2
    latest = await client.get("/v1/playbooks/release-check", headers=member)
    assert latest.status_code == 200, latest.text
    assert latest.json() == second.json()


async def test_a_publish_with_a_finding_lands_and_answers_it_beside_the_version(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    retrying = {**DRAFT, "gates": [], "body": "1. Deploy.\n2. Keep retrying until it is green."}
    published = await client.post("/v1/playbooks", headers=ajax.owner, json=retrying)
    assert published.status_code == 201, published.text
    assert published.json()["version"] == 1
    (finding,) = published.json()["findings"]
    assert finding["check"] == "unbounded_retry"
    assert finding["excerpt"] == "Keep retrying until it is green."
    latest = await client.get("/v1/playbooks/release-check", headers=ajax.owner)
    assert latest.json() == published.json()
    plain = {**retrying, "body": "1. Deploy.\n2. Retry once, then say what failed."}
    second = await client.post("/v1/playbooks", headers=ajax.owner, json=plain)
    assert (second.json()["version"], second.json()["findings"]) == (2, [])


async def test_a_viewer_reads_playbooks_and_publishes_none(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    viewer = await person(client, container, ajax.org_id, Role.VIEWER)
    await client.post("/v1/playbooks", headers=ajax.owner, json=DRAFT)
    assert (await client.get("/v1/playbooks/release-check", headers=viewer)).status_code == 200
    refused(await client.post("/v1/playbooks", headers=viewer, json=DRAFT), 403, "not_authorized")
    latest = await client.get("/v1/playbooks/release-check", headers=viewer)
    assert latest.json()["version"] == 1


async def test_another_tenants_playbook_is_not_found(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    bravo = await tenant(client, container, "bravo")
    await client.post("/v1/playbooks", headers=ajax.owner, json=DRAFT)
    refused(await client.get("/v1/playbooks/release-check", headers=bravo.owner), 404, "not_found")
    # Bravo's own version of the name starts at one and leaves Ajax's as it is.
    own = await client.post("/v1/playbooks", headers=bravo.owner, json=DRAFT)
    assert own.json()["version"] == 1
    assert (await client.get("/v1/playbooks/release-check", headers=ajax.owner)).json()[
        "version"
    ] == 1


async def test_a_malformed_draft_is_refused_whole(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    bad = [
        {**DRAFT, "name": "Release Check"},
        {**DRAFT, "body": ""},
        {**DRAFT, "gates": [{"tool": "git_push", "decision": "allow"}]},
        {**DRAFT, "gates": [{"decision": "deny"}]},
        {**DRAFT, "gates": [{"tool": "Git Push", "decision": "deny"}]},
    ]
    for body in bad:
        response = await client.post("/v1/playbooks", headers=ajax.owner, json=body)
        refused(response, 422, "validation_failed")
    refused(await client.get("/v1/playbooks/release-check", headers=ajax.owner), 404, "not_found")
    refused(
        await client.get("/v1/playbooks/Not%20A%20Name", headers=ajax.owner),
        422,
        "validation_failed",
    )


async def test_a_version_the_checks_never_read_answers_null_never_an_empty_list(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    # A version as a release before the checks wrote it.
    before = Playbook(
        id=new_id(),
        created_at=utcnow(),
        name="release-check",
        version=1,
        description="What a release needs before it ships.",
        body="1. Keep retrying until it is green.",
        published_by=new_id(),
    )
    await container.storage.get_playbook_storage().create_playbook(ajax.org_id, before, ())
    read = await client.get("/v1/playbooks/release-check", headers=ajax.owner)
    assert read.status_code == 200, read.text
    assert read.json()["findings"] is None
    plain = {**DRAFT, "body": "1. Deploy.\n2. Retry once, then say what failed."}
    second = await client.post("/v1/playbooks", headers=ajax.owner, json=plain)
    assert (second.json()["version"], second.json()["findings"]) == (2, [])
