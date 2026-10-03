"""A tenant's own provider keys over the live app, in memory: a key is
written and never comes back, in no response and no error; the tenant sees
who added each key, when, and its state; a member who may not manage the
org writes none; and a process with no probe saves none."""

from pathlib import Path
from uuid import UUID

import httpx
import pytest
from api_support import add_member, build_container, client_over, sign_in, sign_in_as

from acme.om.context import Role
from acme.om.trust.types.provider_key import key_secret_name
from acme.services.api.container import AppContainer

VALUE = "sk-ant-the-tenants-own-key-0123456789"
ROTATED = "sk-ant-the-tenants-next-key-9876543210"


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    """Beside the scripted providers, which stand in for every model, the
    probe's twin takes every key."""
    return build_container(tmp_path, model_providers="scripted")


async def test_a_key_is_written_and_never_read_back_and_its_status_is_shown(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    saved = await client.put("/v1/provider-keys/anthropic", headers=owner, json={"value": VALUE})
    assert saved.status_code == 200, saved.text
    first = saved.json()
    assert first["provider"] == "anthropic" and first["status"] == "live"
    assert set(first) == {"id", "provider", "status", "created_at", "created_by", "last_used_at"}
    assert VALUE not in saved.text

    rotated = await client.put(
        "/v1/provider-keys/anthropic", headers=owner, json={"value": ROTATED}
    )
    assert rotated.status_code == 200, rotated.text
    listed = await client.get("/v1/provider-keys", headers=owner)
    assert listed.status_code == 200, listed.text
    assert [(key["id"], key["status"]) for key in listed.json()] == [
        (rotated.json()["id"], "live"),
        (first["id"], "rotated"),
    ]
    assert VALUE not in listed.text and ROTATED not in listed.text

    # The value lives in the secret store under its reference, and nowhere
    # the API answers from.
    org_id = (await client.get("/v1/orgs/current", headers=owner)).json()["id"]
    secrets = container.infra.get_secrets()
    stored = await secrets.get(UUID(org_id), key_secret_name(UUID(rotated.json()["id"])))
    assert stored == ROTATED


async def test_a_refused_value_comes_back_in_no_error(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    too_long = "sk-" + "x" * 5000
    refused = await client.put(
        "/v1/provider-keys/anthropic", headers=owner, json={"value": too_long}
    )
    assert refused.status_code == 422, refused.text
    assert too_long not in refused.text and "xxxx" not in refused.text
    unknown = await client.put("/v1/provider-keys/acme", headers=owner, json={"value": VALUE})
    assert unknown.status_code == 422 and VALUE not in unknown.text
    assert (await client.get("/v1/provider-keys", headers=owner)).json() == []


async def test_a_member_who_may_not_manage_the_org_saves_no_key(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    org_id = (await client.get("/v1/orgs/current", headers=owner)).json()["id"]
    await add_member(container, UUID(org_id), "mia@example.test", Role.MEMBER)
    member = await sign_in_as(client, "mia@example.test", UUID(org_id))
    refused = await client.put("/v1/provider-keys/openai", headers=member, json={"value": VALUE})
    assert refused.status_code == 403, refused.text
    assert VALUE not in refused.text
    assert (await client.get("/v1/provider-keys", headers=owner)).json() == []


async def test_a_process_with_no_probe_saves_no_key(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    async with client_over(container) as client:
        owner = await sign_in(client, container)
        refused = await client.put(
            "/v1/provider-keys/anthropic", headers=owner, json={"value": VALUE}
        )
        assert refused.status_code == 503, refused.text
        assert VALUE not in refused.text
        assert (await client.get("/v1/provider-keys", headers=owner)).json() == []
