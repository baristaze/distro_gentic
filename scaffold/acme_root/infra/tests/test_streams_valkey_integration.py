"""The Valkey streams impl over the compose stack's Valkey: each bound holds
on the server, a group reads its own streams alone, and an idle stream
expires."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest

from acme.infra.base import new_id
from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.impl.settings import InfraSettings
from acme.infra.impl.valkey import ValkeyConnection
from acme.infra.streams import StreamBounds
from acme.infra.streams.valkey import PREFIX, StreamsValkeyImpl

pytestmark = pytest.mark.integration


@pytest.fixture
async def infra() -> AsyncIterator[InfraConfiguredImpl]:
    settings = InfraSettings.model_validate(
        {
            "environment": "local",
            "cache_backend": "valkey",
            "topics_backend": "valkey",
            "valkey_url": InfraSettings().valkey_url,
        }
    )
    root = InfraConfiguredImpl(settings)
    await root.start()
    try:
        yield root
    finally:
        await root.close()


async def test_a_stream_holds_at_most_its_cap_and_its_group_reads_it_alone() -> None:
    """Each bound holds on the server, and a group's read finds its own
    streams and no other group's."""
    settings = InfraSettings()
    connection = ValkeyConnection(
        settings.valkey_url, timedelta(seconds=settings.valkey_timeout_seconds)
    )
    try:
        streams = StreamsValkeyImpl(connection)
        client = await connection.client()
        assert client is not None
        bounds = StreamBounds(entries=4, bytes=1000, streams=2)
        group, stream = new_id(), new_id()
        key = f"{PREFIX}{group}:{stream}"
        await streams.append(group, stream, [(n, f"part {n}".encode()) for n in range(10)], bounds)
        for n in range(10, 20):
            await streams.append(group, stream, [(n, f"part {n}".encode())], bounds)
        assert await client.xlen(key) == 4
        (held,) = await streams.read(group, {stream: 17}, bounds)
        assert (held.first, held.entries) == (16, ((18, b"part 18"), (19, b"part 19")))

        # A number sent again, or out of its order, lands nothing.
        await streams.append(group, stream, [(19, b"again"), (3, b"late")], bounds)
        assert await client.xlen(key) == 4

        # By bytes: the oldest go, and the newest stays even past the bound.
        big = new_id()
        await streams.append(group, big, [(n, b"x" * 400) for n in range(4)], bounds)
        assert await client.xlen(f"{PREFIX}{group}:{big}") == 2
        await streams.append(group, big, [(4, b"y" * 1500)], bounds)
        (alone,) = [s for s in await streams.read(group, {}, bounds) if s.stream == big]
        assert alone.entries == ((4, b"y" * 1500),)

        # By streams: a group's third closes the one that heard nothing longest.
        await streams.append(group, new_id(), [(0, b"third")], bounds)
        assert await client.exists([key]) == 0
        assert stream not in {s.stream for s in await streams.read(group, {}, bounds)}

        # Another group reads nothing of this one's.
        assert await streams.read(new_id(), {big: -1}, bounds) == ()

        # An ended stream goes whole.
        await streams.end(group, big)
        assert await client.exists([f"{PREFIX}{group}:{big}", f"{PREFIX}{group}:{big}:bytes"]) == 0
        assert big not in {s.stream for s in await streams.read(group, {}, bounds)}
    finally:
        await connection.close()


async def test_streams_over_valkey_expire_when_idle(infra: InfraConfiguredImpl) -> None:
    streams = infra.get_streams()
    bounds = StreamBounds(idle=timedelta(milliseconds=200))
    group, stream = new_id(), new_id()
    await streams.append(group, stream, [(0, b"a")], bounds)
    assert [s.stream for s in await streams.read(group, {}, bounds)] == [stream]
    await asyncio.sleep(0.3)
    assert await streams.read(group, {}, bounds) == ()
