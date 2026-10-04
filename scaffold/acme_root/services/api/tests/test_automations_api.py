"""A tenant's automations over the API: a person makes one in a project of
the tenant, reads and lists them, and its creator edits it. A viewer makes
none, and nobody but its creator edits one that runs as its creator, since
it runs on the creator's authority. Another tenant's automation and project
are not found; a malformed automation, and one whose action kind no
product declares, is refused whole. A product's own action, whose params
nest lists and mappings, is made, read, and listed whole."""

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import httpx
from api_support import build_container
from httpx import ASGITransport
from tenant_support import Headers, person, refused, tenant

from acme.om.automations.actions import AutomationActionInterface
from acme.om.automations.types.automation import AutomationRun, RunOutcome
from acme.om.base import Platform, new_id
from acme.om.context import Role, TenantContext
from acme.om.root import Managers, PlatformPorts, ProductKinds
from acme.services.api.app import create_app
from acme.services.api.container import AppContainer

PROJECT = {
    "name": "the weekly reports",
    "repository": {"host": "github.com", "path": "octo/reports"},
}


def automation(project_id: str) -> dict[str, object]:
    return {
        "name": "triage a failed build",
        "trigger": {"kind": "event", "effects": ["ci_failed"]},
        "action": {
            "kind": "start_session",
            "brief": "Find why the build failed and say so on the pull request.",
            "agent_kind": "assistant",
            "title": "a failed build",
            "project_id": project_id,
        },
        "limits": {
            "cost_cap_micros": 5_000_000,
            "run_cap_micros": 1_000_000,
            "rate": 10,
            "concurrency": 2,
        },
    }


async def project_of(client: httpx.AsyncClient, owner: Headers) -> str:
    made = await client.post("/v1/projects", headers=owner, json=PROJECT)
    assert made.status_code == 201, made.text
    return made.json()["id"]


async def test_a_person_makes_reads_lists_and_edits_an_automation(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    member = await person(client, container, ajax.org_id, Role.MEMBER)
    body = automation(await project_of(client, ajax.owner))
    made = await client.post("/v1/automations", headers=member, json=body)
    assert made.status_code == 201, made.text
    view = made.json()
    assert view["runs_as"] == "creator" and view["enabled"] is True
    assert view["limits"]["period"] == "P1D"
    url = f"/v1/automations/{view['id']}"
    assert (await client.get(url, headers=ajax.owner)).json() == view
    listed = await client.get("/v1/automations", headers=ajax.owner)
    assert [a["id"] for a in listed.json()] == [view["id"]]
    every = {"kind": "schedule", "every": 3600}
    edited = await client.put(
        url, headers=member, json={**body, "trigger": every, "enabled": False}
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["trigger"]["kind"] == "schedule"
    assert edited.json()["enabled"] is False
    assert edited.json()["created_by"] == view["created_by"]
    assert (await client.get(url, headers=member)).json() == edited.json()


async def test_only_its_creator_edits_one_that_runs_as_its_creator(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    member = await person(client, container, ajax.org_id, Role.MEMBER)
    body = automation(await project_of(client, ajax.owner))
    made = (await client.post("/v1/automations", headers=member, json=body)).json()
    url = f"/v1/automations/{made['id']}"
    taken = await client.put(url, headers=ajax.owner, json={**body, "name": "the owner's now"})
    refused(taken, 403, "not_authorized")
    # Running as the principal is a grant's authority, not the creator's: an
    # owner whose role holds the grant edits it and is its creator from then
    # on, so the member who made it no longer turns it back.
    grant = await client.put(
        "/v1/automations/principal", headers=ajax.owner, json={"role": "member"}
    )
    assert grant.status_code == 200, grant.text
    principal = {**body, "runs_as": "automation_principal"}
    moved = await client.put(url, headers=ajax.owner, json=principal)
    assert moved.status_code == 200, moved.text
    assert moved.json()["created_by"] != made["created_by"]
    viewer = await person(client, container, ajax.org_id, Role.VIEWER)
    refused(await client.put(url, headers=viewer, json=principal), 403, "not_authorized")
    back = await client.put(url, headers=member, json=body)
    refused(back, 403, "not_authorized")
    assert (await client.get(url, headers=member)).json()["runs_as"] == "automation_principal"


async def test_a_viewer_reads_automations_and_makes_none(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    viewer = await person(client, container, ajax.org_id, Role.VIEWER)
    body = automation(await project_of(client, ajax.owner))
    refused(await client.post("/v1/automations", headers=viewer, json=body), 403, "not_authorized")
    assert (await client.get("/v1/automations", headers=viewer)).json() == []
    principal = {**body, "runs_as": "automation_principal"}
    ungranted = await client.post("/v1/automations", headers=ajax.owner, json=principal)
    refused(ungranted, 403, "not_authorized")


async def test_another_tenants_automation_and_project_are_not_found(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    bravo = await tenant(client, container, "bravo")
    body = automation(await project_of(client, ajax.owner))
    made = (await client.post("/v1/automations", headers=ajax.owner, json=body)).json()
    url = f"/v1/automations/{made['id']}"
    refused(await client.get(url, headers=bravo.owner), 404, "not_found")
    refused(await client.put(url, headers=bravo.owner, json=body), 404, "not_found")
    # A start in another tenant's project is refused before anything is saved.
    refused(await client.post("/v1/automations", headers=bravo.owner, json=body), 404, "not_found")
    assert (await client.get("/v1/automations", headers=bravo.owner)).json() == []
    assert (await client.get(url, headers=ajax.owner)).json() == made


async def test_a_malformed_automation_is_refused_whole(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    body = automation(await project_of(client, ajax.owner))
    action, limits = dict(body["action"]), dict(body["limits"])  # type: ignore[arg-type]
    bad = [
        {**body, "trigger": {"kind": "schedule", "every": 30}},
        {**body, "trigger": {"kind": "schedule", "every": 3600, "effects": ["ci_failed"]}},
        {**body, "trigger": {"kind": "event", "every": 3600}},
        {**body, "action": {**action, "title": None}},
        {**body, "action": {**action, "project_id": None}},
        {**body, "action": {**action, "kind": "message_session"}},
        {**body, "action": {**action, "brief": None}},
        {**body, "action": {**action, "params": {"steps": 2}}},
        # A kind no product declares could never act.
        {**body, "action": {"kind": "run_job", "params": {"steps": 2}}},
        {**body, "action": {"kind": "Run Job"}},
        {**body, "limits": {**limits, "run_cap_micros": 6_000_000}},
        {**body, "limits": {**limits, "rate": 0}},
        {**body, "created_by": "00000000-0000-0000-0000-000000000000"},
    ]
    for each in bad:
        response = await client.post("/v1/automations", headers=ajax.owner, json=each)
        refused(response, 422, "validation_failed")
    assert (await client.get("/v1/automations", headers=ajax.owner)).json() == []


class Sweep(Platform):
    steps: int
    on: tuple[str, ...]
    where: dict[str, tuple[str, ...]]


class SweepAction(AutomationActionInterface):
    """A product's kind whose params nest a list and a mapping."""

    name = "sweep"
    params = Sweep

    async def act(self, ctx: TenantContext, run: AutomationRun, params: Platform) -> UUID:
        return new_id()

    async def ended(self, ctx: TenantContext, run: AutomationRun) -> RunOutcome | None:
        return None


def sweeping(managers: Callable[[], Managers]) -> tuple[AutomationActionInterface, ...]:
    return (SweepAction(),)


async def test_a_products_action_with_nested_params_is_made_read_and_listed(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path, ports=PlatformPorts(kinds=ProductKinds(actions=sweeping)))
    app = create_app(container)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            ajax = await tenant(client, container, "ajax")
            params = {"steps": 2, "on": ["a", "b"], "where": {"lab": ["north", "south"]}}
            body = {
                **automation(await project_of(client, ajax.owner)),
                "action": {"kind": "sweep", "params": params},
            }
            made = await client.post("/v1/automations", headers=ajax.owner, json=body)
            assert made.status_code == 201, made.text
            assert made.json()["action"]["params"] == params
            read = await client.get(f"/v1/automations/{made.json()['id']}", headers=ajax.owner)
            assert read.status_code == 200, read.text
            assert read.json() == made.json()
            listed = await client.get("/v1/automations", headers=ajax.owner)
            assert listed.status_code == 200, listed.text
            assert listed.json() == [made.json()]
