"""The tenant's tool policy over the API: any member reads the layer, and an
owner or an admin writes it whole on the version they read. A member writes
none; each tenant reads and writes its own; a malformed layer, an approver
that is a service among them, is refused whole."""

import httpx
from tenant_support import person, refused, tenant

from acme.om.context import Role
from acme.services.api.container import AppContainer

LAYER = {
    "rules": [
        {"authorization_class": "outward_write", "decision": "approve"},
        {
            "tool": "git_push",
            "target_kind": "branch",
            "target": {"protected": True},
            "decision": "deny",
        },
    ],
    "approvers": [{"authorization_class": "outward_write", "roles": ["owner"]}],
}


def at(headers: dict[str, str], version: int) -> dict[str, str]:
    return {**headers, "If-Match": f'"{version}"'}


async def test_an_admin_writes_the_layer_on_the_version_read(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    admin = await person(client, container, ajax.org_id, Role.ADMIN)
    empty = await client.get("/v1/tools/policy", headers=admin)
    assert empty.status_code == 200, empty.text
    assert empty.json()["rules"] == [] and empty.json()["version"] == 1
    written = await client.put("/v1/tools/policy", headers=at(admin, 1), json=LAYER)
    assert written.status_code == 200, written.text
    assert written.json()["version"] == 1
    assert written.json()["rules"][1]["target"] == {"protected": True}
    changed = await client.put(
        "/v1/tools/policy", headers=at(ajax.owner, 1), json={**LAYER, "approvers": []}
    )
    assert changed.json()["version"] == 2
    assert changed.json()["approvers"] == []
    stale = await client.put("/v1/tools/policy", headers=at(admin, 1), json=LAYER)
    refused(stale, 412, "precondition_failed")
    unnamed = await client.put("/v1/tools/policy", headers=admin, json=LAYER)
    refused(unnamed, 422, "validation_failed")
    assert (await client.get("/v1/tools/policy", headers=admin)).json() == changed.json()


async def test_a_member_reads_the_layer_and_writes_none(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    for role in (Role.MEMBER, Role.VIEWER):
        headers = await person(client, container, ajax.org_id, role)
        assert (await client.get("/v1/tools/policy", headers=headers)).status_code == 200
        response = await client.put("/v1/tools/policy", headers=at(headers, 1), json=LAYER)
        refused(response, 403, "not_authorized")
    assert (await client.get("/v1/tools/policy", headers=ajax.owner)).json()["rules"] == []


async def test_each_tenant_reads_and_writes_its_own_layer(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    bravo = await tenant(client, container, "bravo")
    await client.put("/v1/tools/policy", headers=at(ajax.owner, 1), json=LAYER)
    theirs = await client.get("/v1/tools/policy", headers=bravo.owner)
    assert theirs.json()["rules"] == [] and theirs.json()["approvers"] == []
    own = await client.put("/v1/tools/policy", headers=at(bravo.owner, 1), json={"rules": []})
    assert own.status_code == 200, own.text
    kept = await client.get("/v1/tools/policy", headers=ajax.owner)
    assert len(kept.json()["rules"]) == 2


async def test_a_malformed_layer_is_refused_whole(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    bad = [
        {"approvers": [{"authorization_class": "outward_write", "roles": ["service"]}]},
        {"approvers": [{"authorization_class": "outward_write", "roles": []}]},
        {
            "approvers": [
                {"authorization_class": "outward_write", "roles": ["owner"]},
                {"authorization_class": "outward_write", "roles": ["admin"]},
            ]
        },
        {"rules": [{"tool": "Bad Tool", "decision": "deny"}]},
        {"rules": [{"decision": "maybe"}]},
        {"rules": [{"decision": "deny", "target": {"nested": {"a": 1}}}]},
    ]
    for body in bad:
        response = await client.put("/v1/tools/policy", headers=at(ajax.owner, 1), json=body)
        refused(response, 422, "validation_failed")
    assert (await client.get("/v1/tools/policy", headers=ajax.owner)).json()["rules"] == []
