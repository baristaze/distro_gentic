"""A restore's parts reach a VM's directory by its host's own fetch,
against the live app, in process (ADR 2077). The parts of a session's
archive sit in the snapshots bucket, each sealed under a key of its own:
the runner hands the host each one's key and a link signed for it alone,
`FETCHED` to an item, and the host fetches an item's parts at once,
straight from the store, checks each against its size and its digest, and
writes it whole into the directory's kept folder. No byte of a part
crosses the runner. A part whose bytes do not match its digest loses the
restore: nothing of it is written, and every part kept stands as it was."""

import asyncio
import base64
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from host_support import Stack
from test_exec_relay import claims, relay_to

from acme.infra.agent_workspaces import AgentWorkspaceLost
from acme.infra.buckets import Buckets
from acme.infra.buckets.sealed import digest_of, new_key, seal_object
from acme.om.agent_workspaces.impl import pool_directory
from acme.om.agent_workspaces.impl.pool_directory import KEPT
from acme.om.base import new_id
from acme.om.exec_relay.types.exec import FETCHED, ObjectRef
from acme.om.tools.impl.snapshots import CONTENT_TYPE, part_key

PART = 64 * 1024
"""A part, small enough that a case holds many."""


class AtOnce(httpx.AsyncBaseTransport):
    """The store, holding each GET until `together` are in flight or a
    second passes, and counting the most that ever were: what a host that
    fetches its parts at once reaches, and one that fetches them in turn
    never does."""

    def __init__(self, inner: httpx.AsyncBaseTransport, together: int) -> None:
        self._inner = inner
        self._together = together
        self._flying = 0
        self._met = asyncio.Event()
        self.most = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            return await self._inner.handle_async_request(request)
        self._flying += 1
        self.most = max(self.most, self._flying)
        if self._flying >= self._together:
            self._met.set()
        try:
            await asyncio.wait_for(self._met.wait(), 1)
        except TimeoutError:
            pass
        try:
            return await self._inner.handle_async_request(request)
        finally:
            self._flying -= 1


async def kept(api: Stack, agent_session_id: UUID, parts: list[bytes]) -> list[ObjectRef]:
    """An archive of the session's in the snapshots bucket: each part sealed
    under a key of its own where it is kept, as the objects a restore hands
    the session's VM."""
    snapshot_id = new_id()
    buckets = api.container.infra.get_buckets()
    named: list[ObjectRef] = []
    for index, data in enumerate(parts):
        reference = part_key(agent_session_id, snapshot_id, index)
        key = new_key()
        sealed = seal_object(key, reference, data)
        await buckets.put(api.owner.org_id, Buckets.SNAPSHOTS, reference, sealed, CONTENT_TYPE)
        named.append(
            ObjectRef(
                reference=reference,
                size=len(data),
                digest=digest_of(data),
                key=base64.b64encode(key).decode(),
            )
        )
    return named


async def stored(api: Stack, parts: list[ObjectRef]) -> list[bytes]:
    buckets = api.container.infra.get_buckets()
    return [
        await buckets.get(api.owner.org_id, Buckets.SNAPSHOTS, part.reference) for part in parts
    ]


async def test_a_restores_parts_reach_the_vm_by_its_hosts_own_fetch_at_once_and_never_the_runner(
    api: Stack, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert api.store is not None
    store = AtOnce(api.store, together=4)
    relayed = await relay_to(replace(api, store=store), tmp_path)
    parts = [os.urandom(PART) for _ in range(FETCHED)] + [os.urandom(PART // 3) for _ in range(3)]
    named = await kept(api, relayed.workspace.id, parts)
    # Every read the platform's own store makes, by key: the store a link
    # names serves its file itself.
    buckets = api.container.infra.get_buckets()
    get = buckets.get
    read: list[str] = []

    async def noted(
        org_id: UUID, bucket: Buckets, key: str, *, deadline: datetime | None = None
    ) -> bytes:
        read.append(key)
        return await get(org_id, bucket, key, deadline=deadline)

    monkeypatch.setattr(buckets, "get", noted)

    fetching = asyncio.ensure_future(
        pool_directory.fetch(relayed.runner, relayed.workspace, named, epoch=relayed.epoch)
    )
    handed = await claims(relayed.host, fetching)
    await fetching

    folder = tmp_path / "workspace" / KEPT
    assert [(folder / f"part-{index:06d}").read_bytes() for index in range(len(parts))] == parts
    assert len(set(handed)) == 2, f"{FETCHED} parts to an item, then the rest"
    assert store.most >= 4, "an item's parts fetched at once"
    assert not [key for key in read if "/workspace/" in key], "no part read by the runner"


async def test_a_part_whose_bytes_do_not_match_its_digest_loses_the_restore_and_nothing_kept(
    api: Stack, tmp_path: Path
) -> None:
    relayed = await relay_to(api, tmp_path)
    named = await kept(api, relayed.workspace.id, [os.urandom(PART) for _ in range(3)])
    # The second sealed again under its own key at its own place: it opens,
    # to bytes of its size its digest does not name.
    other = named[1]
    resealed = seal_object(base64.b64decode(other.key), other.reference, b"x" * other.size)
    await api.container.infra.get_buckets().put(
        api.owner.org_id, Buckets.SNAPSHOTS, other.reference, resealed, CONTENT_TYPE
    )
    before = await stored(api, named)

    fetching = asyncio.ensure_future(
        pool_directory.fetch(relayed.runner, relayed.workspace, named, epoch=relayed.epoch)
    )
    await claims(relayed.host, fetching)
    with pytest.raises(AgentWorkspaceLost, match="did not reach the VM whole"):
        await fetching

    assert not (tmp_path / "workspace" / KEPT / "part-000001").exists(), "nothing of it written"
    assert await stored(api, named) == before, "every part kept as it was"
