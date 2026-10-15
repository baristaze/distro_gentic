"""A namespace a product declares beside its kinds, and nowhere else: the
maintenance worker builds its managers once and runs its purge of a deleted
tenant in the order it names, before the purge it runs ahead of, with no
wiring file naming it."""

from datetime import timedelta
from pathlib import Path

import pytest
from worker_support import build_container, request

from acme.om import product_namespaces
from acme.om.base import new_id, utcnow
from acme.om.context import Role
from acme.workers.maintenance.main import build_loop

from contracts.product_namespace import NAMESPACES, PARCELS, Parcels


@pytest.fixture(autouse=True)
def declared(monkeypatch: pytest.MonkeyPatch) -> None:
    """The product's declaration beside its kinds holds `parcels`."""
    monkeypatch.setattr(product_namespaces, "PRODUCT_NAMESPACES", NAMESPACES)


async def test_a_declared_namespaces_purge_runs_before_the_purge_it_names(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    (swept,) = container.platform.products
    parcels = swept.managers
    assert isinstance(parcels, Parcels)
    loop = build_loop(container)
    order = list(loop._purges)  # pyright: ignore[reportPrivateUsage]
    assert order.index(PARCELS) == order.index("events") - 1, "just before the events' purge"

    # A team org deleted past its retention, with a parcel, and an api key
    # whose making its stream records.
    tail = new_id().hex[-8:]
    owner, org = await container.managers.tenancy.bootstrap(
        request(), "Gone", f"gone-{tail}", f"gone-{tail}@example.test", "Gone"
    )
    await parcels.add(owner, "crate")
    await container.managers.tenancy.credentials.create_api_key(owner, "ci", Role.MEMBER)
    events = container.storage.get_change_event_storage()
    assert await events.read_after(org.id, 0, 100), "the stream holds its events"
    tenancy = container.storage.get_tenancy_storage()
    stored = await tenancy.read_org(org.id)
    assert stored is not None
    when = utcnow() - timedelta(days=40)
    await tenancy.write_org(org.id, stored.model_copy(update={"deleted_at": when}))

    await loop._sweep_once()  # pyright: ignore[reportPrivateUsage]

    ((purged, events_left),) = [found for found in parcels.found if found[0] == org.id]
    assert purged == org.id and events_left > 0, "it ran while the tenant's events stood"
    assert await parcels.list(owner) == [], "its rows went"
    assert await events.read_after(org.id, 0, 100) == [], "the events' purge ran after it"
