"""The host's control stream, opened again whenever it ends. Once the
platform ended one, it pauses a while, half of it jitter; once one failed,
it waits the claimant kit's wait, a 429's ask honored and the cap held,
and a message heard starts that wait over. Hosts whose streams fail
together, with their own jitter each, open the next apart."""

from collections.abc import Callable

import httpx
import pytest

from acme.apps.host.main import REOPEN_SECONDS, listen
from acme.client.claimant.backoff import BACKOFF_MAX_SECONDS
from acme.client.transport import ApiError


class Done(Exception):
    """Ends the loop once the streams run out."""


WIRE = httpx.ConnectError("connection refused")
SLOW_DOWN = ApiError(429, "rate_limited", "slow down", None, retry_after=7.0)
LONG_ASK = ApiError(429, "rate_limited", "slow down", None, retry_after=600.0)


class Streams:
    """A host whose streams go as listed: each hears that many messages, and
    then ends, or raises what it names."""

    def __init__(self, *streams: tuple[int, Exception | None]) -> None:
        self._streams = list(streams)

    async def listen(self, heard: Callable[[], None]) -> None:
        if not self._streams:
            raise Done
        messages, raised = self._streams.pop(0)
        for _ in range(messages):
            heard()
        if raised is not None:
            raise raised


async def waits_of(streams: Streams, jitter: Callable[[], float]) -> list[float]:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    with pytest.raises(Done):
        await listen(streams, sleep=sleep, jitter=jitter)  # type: ignore[arg-type]
    return waits


def drawn(*values: float) -> Callable[[], float]:
    draws = iter(values)
    return lambda: next(draws)


async def test_a_stream_the_platform_ended_is_opened_again_after_a_jittered_pause() -> None:
    waits = await waits_of(Streams((1, None), (3, None), (1, None)), drawn(0.0, 0.5, 1.0))
    assert waits == [REOPEN_SECONDS / 2, REOPEN_SECONDS * 3 / 4, REOPEN_SECONDS]


async def test_a_stream_that_fails_waits_the_kits_backoff_with_a_429_honored_and_the_cap() -> None:
    failures = Streams((0, WIRE), (0, WIRE), (0, SLOW_DOWN), *[(0, WIRE)] * 6, (0, LONG_ASK))
    waits = await waits_of(failures, lambda: 1.0)
    assert waits == [1.0, 2.0, 7.0, 8.0, 16.0, 32.0, 64.0, 120.0, 120.0, BACKOFF_MAX_SECONDS]
    # Another host, failing at the same moments, draws its own jitter.
    failures = Streams((0, WIRE), (0, WIRE), (0, SLOW_DOWN), *[(0, WIRE)] * 6, (0, LONG_ASK))
    apart = await waits_of(failures, lambda: 0.0)
    assert apart == [0.5, 1.0, 7.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0, BACKOFF_MAX_SECONDS]


async def test_a_message_heard_starts_the_wait_over() -> None:
    streams = Streams((0, WIRE), (0, WIRE), (0, WIRE), (2, WIRE), (0, WIRE))
    assert await waits_of(streams, lambda: 1.0) == [1.0, 2.0, 4.0, 1.0, 2.0]
