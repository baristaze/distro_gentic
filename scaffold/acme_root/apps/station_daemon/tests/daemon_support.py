"""The whole API in-process behind a station daemon: the app runs inside its
lifespan, and the daemon's client reaches it through a transport a case can
cut, as a lost network cuts it. The owner's stations file is written on the
daemon's home, and the monotonic clock is a case's to move."""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from api_support import build_container, seed_request
from contracts.agent_session_storage import make_session
from contracts.step_storage import make_message, make_request
from fastapi import FastAPI

from acme.apps.station_daemon import stations as owner_stations
from acme.apps.station_daemon.adapter import Outcome, StationTwinImpl
from acme.apps.station_daemon.config import Settings
from acme.apps.station_daemon.daemon import StationDaemon
from acme.client.client import ApiClient
from acme.om.base import new_id, utcnow
from acme.om.context import TenantContext
from acme.om.stations.rules import LINE_PARK
from acme.om.stations.types.job import StationCommand
from acme.om.stations.types.lease import StationLease
from acme.om.stations.types.line import StationAsk
from acme.om.stations.types.station import Lab, Station, StationPool
from acme.services.api.app import create_app
from acme.services.api.container import AppContainer

STATIONS_TOML = """
[[stations]]
id = "{station_id}"
name = "station-1"
adapter = "twin"
devices = ["/dev/station0"]
operations = ["apply", "measure"]
controlled_stop = "hold"

[stations.baseline]
speed = 0.0

[stations.limits.speed]
max = 1.0
"""


class Cuttable(httpx.AsyncBaseTransport):
    """The way to the platform, which a case cuts and mends."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner
        self.cut = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.cut:
            raise httpx.ConnectError("the platform cannot be reached", request=request)
        return await self._inner.handle_async_request(request)


class Monotonic:
    """A monotonic clock a case moves."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class SlowTwin(StationTwinImpl):
    """The twin, with each operation taking `seconds` on the case's clock."""

    def __init__(self, station: owner_stations.Station, clock: Monotonic, seconds: float) -> None:
        super().__init__(station)
        self._clock = clock
        self._seconds = seconds

    async def run(self, operation: str, parameters: Mapping[str, Any]) -> Outcome:
        self._clock.now += self._seconds
        return await super().run(operation, parameters)


@dataclass
class Stack:
    container: AppContainer
    transport: Cuttable
    owner: TenantContext
    lab: Lab
    pool: StationPool
    station: Station

    def client(self, token: str | None) -> ApiClient:
        return ApiClient(
            "http://test",
            app="api",
            app_version="station-daemon@test",
            token=token,
            transport=self.transport,
        )

    def settings(self, home: Path, first: str | None) -> Settings:
        home.mkdir(parents=True, exist_ok=True)
        (home / "stations.toml").write_text(STATIONS_TOML.format(station_id=self.station.id))
        return Settings(api_url="http://test", home=home, first_credential=first)

    async def credential(self) -> str:
        issued = await self.container.managers.stations.issue_daemon_credential(
            self.owner, self.lab.id
        )
        return issued.credential

    async def daemon(
        self, home: Path, *, clock: Monotonic | None = None, seconds: float = 0.0
    ) -> tuple[StationDaemon, StationTwinImpl]:
        """A started daemon over the stations file, and its station's twin."""
        settings = self.settings(home, await self.credential())
        held = owner_stations.load(settings.stations_path)
        monotonic = clock or Monotonic()
        twin = SlowTwin(held[self.station.id], monotonic, seconds)
        daemon = StationDaemon(
            settings, held, {self.station.id: twin}, self.client, monotonic=monotonic
        )
        await daemon.start()
        return daemon, twin

    async def granted(self) -> StationLease:
        """A session parked on the station's line, and granted it."""
        managers = self.container.managers
        ctx = self.owner
        session = await managers.agent_sessions.create_session(ctx, make_session())
        (message,) = await managers.steps.append_inputs(ctx, session.id, [make_message(session.id)])
        epoch = await managers.steps.begin_run(ctx, session.id)
        await managers.steps.append_steps(
            ctx, session.id, epoch, [make_request(session.id, message.id, (message.id,))]
        )
        await managers.agent_sessions.park(ctx, session.id, epoch, message.id, LINE_PARK)
        placed = await managers.stations.join(
            ctx,
            new_id(),
            StationAsk(
                session_id=session.id,
                pool_id=self.pool.id,
                station_id=self.station.id,
                project="acme/firmware",
                candidate="4f0405f",
                procedure="smoke",
                procedure_version="v1",
            ),
        )
        assert placed.entry.lease_id is not None
        lease = await managers.stations._storage.read_lease(  # pyright: ignore[reportAttributeAccessIssue]
            ctx.org_id, placed.entry.lease_id
        )
        assert lease is not None
        return lease

    async def job(self, lease: StationLease, *speeds: float) -> UUID:
        job = await self.container.managers.stations.submit_job(
            self.owner,
            new_id(),
            lease.id,
            [StationCommand(operation="apply", parameters={"speed": speed}) for speed in speeds],
        )
        return job.id


@asynccontextmanager
async def stack(tmp_path: Path) -> AsyncIterator[Stack]:
    container = build_container(tmp_path)
    app: FastAPI = create_app(container)
    async with app.router.lifespan_context(app):
        owner, _ = await container.managers.tenancy.bootstrap(
            seed_request(), "Ajax", "ajax", "ann@example.test", "Ann"
        )
        stations = container.managers.stations
        now = utcnow()
        made: dict[str, Any] = {
            "created_at": now,
            "updated_at": now,
            "created_by": owner.user_id,
            "updated_by": owner.user_id,
        }
        lab = await stations.create_lab(owner, Lab(id=new_id(), **made, name="lab-1"))
        pool = await stations.create_pool(owner, StationPool(id=new_id(), **made, name="pool-1"))
        station = await stations.add_station(
            owner,
            Station(
                id=new_id(),
                **made,
                lab_id=lab.id,
                pool_id=pool.id,
                name="station-1",
                hold_seconds=60,
            ),
        )
        transport = Cuttable(httpx.ASGITransport(app=app, raise_app_exceptions=False))
        yield Stack(
            container=container,
            transport=transport,
            owner=owner,
            lab=lab,
            pool=pool,
            station=station,
        )
