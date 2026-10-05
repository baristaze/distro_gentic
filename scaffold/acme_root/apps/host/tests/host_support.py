"""The whole API in-process behind a host: the app runs inside its lifespan,
and the host's client reaches it through a transport that streams each
answer as the app sends it, as a server does, and stamps its `Date`, as the
server in front of it does."""

import asyncio
import json
import re
import subprocess
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from email.utils import format_datetime
from pathlib import Path
from uuid import UUID

import httpx
from api_support import build_container, seed_request
from contracts.tools import stand_ins
from fastapi import FastAPI

from acme.apps.host.agent import HostAgent
from acme.apps.host.ceilings import Ceilings
from acme.apps.host.config import Settings
from acme.apps.host.main import host_transports, host_workspaces
from acme.apps.host.probe import Probe, Probes, platform_and_clock
from acme.apps.host.relay import ExecutorRelayImpl
from acme.client.client import ApiClient
from acme.client.types import IsolationMode
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports import TransportInterface
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.local import TransportLocalImpl
from acme.infra.workspaces import IsolationMode as ProviderMode
from acme.infra.workspaces import WorkspaceProviderInterface
from acme.infra.workspaces.host import WorkspaceHostImpl
from acme.om.base import new_id, utcnow
from acme.om.context import TenantContext
from acme.om.hosts.types.pool import HostPool
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.root import StorageInterface
from acme.om.storage.settings import MigrationSettings
from acme.services.api.app import create_app
from acme.services.api.container import AppContainer


class Streamed(httpx.AsyncBaseTransport):
    """The app in-process, its answer handed over once it starts and its
    body as it is sent: httpx's own ASGI transport holds an answer until the
    app ends it, which a control stream never does by itself. Closing the
    answer is the client going away."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = b"".join([chunk async for chunk in request.stream])  # type: ignore[union-attr]
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": request.method,
            "headers": [(key.lower(), value) for key, value in request.headers.raw],
            "scheme": request.url.scheme,
            "path": request.url.path,
            "raw_path": request.url.raw_path.split(b"?")[0],
            "query_string": request.url.query,
            "server": (request.url.host, request.url.port),
            "client": ("127.0.0.1", 123),
            "root_path": "",
        }
        chunks: asyncio.Queue[bytes | None] = asyncio.Queue()
        started: asyncio.Future[tuple[int, list[tuple[bytes, bytes]]]] = (
            asyncio.get_running_loop().create_future()
        )
        gone = asyncio.Event()
        asked = False

        async def receive() -> dict[str, object]:
            nonlocal asked
            if not asked:
                asked = True
                return {"type": "http.request", "body": body, "more_body": False}
            await gone.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, object]) -> None:
            if message["type"] == "http.response.start":
                started.set_result((message["status"], message.get("headers", [])))  # type: ignore[arg-type]
            elif message["type"] == "http.response.body":
                if message.get("body"):
                    await chunks.put(message["body"])  # type: ignore[arg-type]
                if not message.get("more_body"):
                    await chunks.put(None)

        async def serve() -> None:
            try:
                await self._app(scope, receive, send)  # type: ignore[arg-type]
            except Exception as error:
                if not started.done():
                    started.set_exception(error)
            finally:
                await chunks.put(None)

        task = asyncio.ensure_future(serve())
        status, headers = await started

        class Body(httpx.AsyncByteStream):
            async def __aiter__(self) -> AsyncIterator[bytes]:
                while (chunk := await chunks.get()) is not None:
                    yield chunk

            async def aclose(self) -> None:
                gone.set()
                task.cancel()

        return httpx.Response(status, headers=headers, stream=Body())


class Dated(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        response.headers["Date"] = format_datetime(utcnow(), usegmt=True)
        return response


OPEN_EGRESS = {"mode": "open", "hosts": []}
SESSION_TOOLS = stand_ins("read_log", "run_tests")
"""What `make_session` names, so the agents manager classes every tool it
offers."""
DETAIL = re.compile(r"/v1/hosts/me/exec/[0-9a-f-]+")


class Widened(httpx.AsyncBaseTransport):
    """The stack, except that the spec of each prepare a claim hands over,
    and of each `exec` item's detail, opens egress to anywhere, while the
    fields the host's ceilings read stay as the platform wrote them: a
    control plane that asks for more than its fields say. `widened` counts
    the answers it changed."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner
        self.widened = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        path = request.url.path
        claims = request.method == "POST" and path == "/v1/hosts/me/claims"
        detail = request.method == "GET" and DETAIL.fullmatch(path) is not None
        if response.status_code != 200 or not (claims or detail):
            return response
        body = json.loads(await response.aread())
        item = body.get("item") if claims else None
        spec = body.get("spec") if detail else (item or {}).get("payload", {}).get("spec")
        if not isinstance(spec, dict):
            return response
        spec["egress"] = OPEN_EGRESS
        self.widened += 1
        headers = [(k, v) for k, v in response.headers.raw if k.lower() != b"content-length"]
        return httpx.Response(200, headers=headers, content=json.dumps(body).encode())


def passing(name: str) -> Probe:
    return Probe(name, True, "passed in the test")


def failing(name: str) -> Probe:
    return Probe(name, False, "failed in the test")


def probes(*modes: IsolationMode, metadata_answers: bool = False) -> Probes:
    """The startup's own probes of the machine, each passing, and the
    platform's real one; the isolation probes pass for `modes` alone, and
    the metadata probe fails only when `metadata_answers`."""
    return Probes(
        trust_store=lambda: passing("trust_store"),
        proxy=lambda: passing("proxy"),
        platform_and_clock=platform_and_clock,
        metadata=lambda: failing("metadata") if metadata_answers else passing("metadata"),
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

    async def pool(self, name: str = "build") -> HostPool:
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
async def stack(tmp_path: Path, storage: StorageInterface | None = None) -> AsyncIterator[Stack]:
    """Over the memory storage, or over `storage`, where a tenant of its own
    is bootstrapped under a fresh slug."""
    container = build_container(tmp_path, storage, tool_catalog=SESSION_TOOLS)
    app: FastAPI = create_app(container)
    async with app.router.lifespan_context(app):
        slug = "ajax" if storage is None else f"ajax-{new_id().hex[-8:]}"
        email = "ann@example.test" if storage is None else f"ann-{slug}@example.test"
        owner, _ = await container.managers.tenancy.bootstrap(
            seed_request(), "Ajax", slug, email, "Ann"
        )
        transport = Dated(Streamed(app))
        yield Stack(container=container, transport=transport, owner=owner)


def postgres() -> StoragePostgresImpl:
    """A storage root over the database the integration suites read."""
    settings = MigrationSettings()
    settings.refuse_remote()
    return StoragePostgresImpl(
        settings.role_urls(), settings.role_pools(), system_urls=settings.system_role_urls()
    )


async def directory_host(
    api: Stack,
    pool_id: UUID,
    where: Path,
    *,
    name: str = "host-1",
    ceilings: Ceilings | None = None,
) -> tuple[HostAgent, Path]:
    """A host of the pool, started, that makes a directory per workspace
    under its root and runs commands there; its root is answered with it.
    Its ceilings take any project and any egress, and read its root alone,
    unless the case names its own."""
    root = where / "workspaces"
    transport = TransportLocalImpl(where / "records", SecretsLocalImpl(None), BrokerNullImpl())
    host = await started_host(
        api,
        pool_id,
        replace(api.settings(where / "home", None), name=name),
        ceilings
        or Ceilings(
            projects=None,
            min_isolation=IsolationMode.directory,
            egress=None,
            readable=(str(root),),
        ),
        IsolationMode.directory,
        {ProviderMode.HOST: transport},
        {ProviderMode.HOST: WorkspaceHostImpl(root)},
    )
    return host, root


async def container_host(api: Stack, pool_id: UUID, where: Path) -> HostAgent:
    """A host of the pool as the host's `main` wires one: a container per
    workspace on the local Docker, of the default image. Its ceilings take
    any project, and let nothing leave."""
    settings = api.settings(where / "home", None)
    return await started_host(
        api,
        pool_id,
        settings,
        Ceilings(projects=None, min_isolation=IsolationMode.container, egress=frozenset()),
        IsolationMode.container,
        host_transports(settings),
        host_workspaces(settings),
    )


async def started_host(
    api: Stack,
    pool_id: UUID,
    settings: Settings,
    ceilings: Ceilings,
    mode: IsolationMode,
    transports: Mapping[ProviderMode, TransportInterface],
    workspaces: Mapping[ProviderMode, WorkspaceProviderInterface],
) -> HostAgent:
    """A host of the pool, enrolled and started, that probes `mode` alone."""
    agents: list[HostAgent] = []
    executor = ExecutorRelayImpl(
        lambda: agents[0].client(),
        transports,
        workspaces,
        flush_seconds=0.0,
        renew_seconds=0.2,
    )
    host = HostAgent(
        replace(settings, enrollment_token=await api.token(pool_id)),
        ceilings,
        probes(mode),
        api.client,
        executor,
    )
    agents.append(host)
    await host.start()
    return host


def docker_runs() -> bool:
    try:
        reply = subprocess.run(["docker", "version"], capture_output=True, timeout=20)
    except FileNotFoundError, subprocess.TimeoutExpired:
        return False
    return reply.returncode == 0
