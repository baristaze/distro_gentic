"""The whole API in-process behind a host: the app runs inside its lifespan,
and the host's client reaches it through a transport that stamps each
answer's `Date`, as the server in front of it does."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from email.utils import format_datetime
from pathlib import Path
from uuid import UUID

import httpx
from api_support import build_container, seed_request
from fastapi import FastAPI

from acme.apps.host.config import Settings
from acme.apps.host.probe import Probe, Probes, platform_and_clock
from acme.client.client import ApiClient
from acme.client.types import IsolationMode
from acme.om.base import new_id, utcnow
from acme.om.context import TenantContext
from acme.om.hosts.types.pool import HostPool
from acme.services.api.app import create_app
from acme.services.api.container import AppContainer


class Dated(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        response.headers["Date"] = format_datetime(utcnow(), usegmt=True)
        return response


def passing(name: str) -> Probe:
    return Probe(name, True, "passed in the test")


def failing(name: str) -> Probe:
    return Probe(name, False, "failed in the test")


def probes(*modes: IsolationMode) -> Probes:
    """The startup's own probes of the machine, each passing, and the
    platform's real one; the isolation probes pass for `modes` alone."""
    return Probes(
        trust_store=lambda: passing("trust_store"),
        proxy=lambda: passing("proxy"),
        platform_and_clock=platform_and_clock,
        isolation={
            mode: (lambda m=mode: passing(m.value) if m in modes else failing(m.value))
            for mode in IsolationMode
        },
        capabilities={"git": lambda: True},
    )


@dataclass
class Stack:
    container: AppContainer
    transport: httpx.AsyncBaseTransport
    owner: TenantContext

    def client(self, token: str | None) -> ApiClient:
        return ApiClient(
            "http://test", app="api", app_version="host@test", token=token, transport=self.transport
        )

    def settings(self, home: Path, token: str | None) -> Settings:
        return Settings(
            api_url="http://test",
            home=home,
            name="host-1",
            enrollment_token=token,
            workspace_user=None,
        )

    async def pool(self, name: str = "lab") -> HostPool:
        now = utcnow()
        pool = HostPool(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=self.owner.user_id,
            updated_by=self.owner.user_id,
            name=name,
            region="eu-west",
        )
        return await self.container.managers.hosts.create_pool(self.owner, pool)

    async def token(self, pool_id: UUID) -> str:
        issued = await self.container.managers.hosts.issue_enrollment_token(self.owner, pool_id)
        return issued.token


@asynccontextmanager
async def stack(tmp_path: Path) -> AsyncIterator[Stack]:
    container = build_container(tmp_path)
    app: FastAPI = create_app(container)
    async with app.router.lifespan_context(app):
        owner, _ = await container.managers.tenancy.bootstrap(
            seed_request(), "Ajax", "ajax", "ann@example.test", "Ann"
        )
        transport = Dated(httpx.ASGITransport(app=app, raise_app_exceptions=False))
        yield Stack(container=container, transport=transport, owner=owner)
