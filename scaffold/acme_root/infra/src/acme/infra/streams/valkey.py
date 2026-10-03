"""Streams over Valkey, shared by every process on it: a Valkey stream per
open stream, capped by length (`XADD ... MAXLEN`) and by its bytes, an index
of each group's open streams and one of every group's, each scored by when
its stream last heard, and an expiry of the idle time on every key, so a
stream nobody closes goes on its own. Each call is one script, atomic on the
server. An entry's id is `0-<n + 1>`, so the stream refuses a number at or
below its last, and a read resumes after a number by its id.

The append script closes streams other than the ones its keys name (an idle
one, or the one a bound lets go), so it runs on one Valkey, never a
cluster."""

import logging
from collections.abc import Mapping, Sequence
from datetime import timedelta
from uuid import UUID

from glide import GlideClient, GlideError, Script, TEncodable

from acme.infra.impl.valkey import ValkeyConnection
from acme.infra.observability import OUTCOMES
from acme.infra.streams import StreamBounds, StreamsInterface, StreamSlice

log = logging.getLogger(__name__)

PREFIX = "acme:streams:"
OPEN = "acme:streams"
"""Every open stream as `<group>:<stream>`; a group's index is
`acme:streams:<group>`, its stream `acme:streams:<group>:<stream>`, and the
stream's byte count beside it, under `:bytes`."""

_NOW = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
"""

APPEND_SCRIPT = Script(
    _NOW
    + """
local prefix, group, stream = ARGV[1], ARGV[2], ARGV[3]
local max_entries, max_bytes = tonumber(ARGV[4]), tonumber(ARGV[5])
local max_streams, max_open, idle = tonumber(ARGV[6]), tonumber(ARGV[7]), tonumber(ARGV[8])

local function close(member)
  local owner, name = string.match(member, '^([^:]+):(.+)$')
  redis.call('DEL', prefix .. member, prefix .. member .. ':bytes')
  redis.call('ZREM', prefix .. owner, name)
  redis.call('ZREM', KEYS[4], member)
end

for _, member in ipairs(redis.call('ZRANGEBYSCORE', KEYS[4], '-inf', now - idle)) do
  close(member)
end
if redis.call('EXISTS', KEYS[1]) == 0 then
  redis.call('DEL', KEYS[2])
  redis.call('ZREM', KEYS[3], stream)
  if redis.call('ZCARD', KEYS[3]) >= max_streams then
    close(group .. ':' .. redis.call('ZRANGE', KEYS[3], 0, 0)[1])
  end
  if redis.call('ZCARD', KEYS[4]) >= max_open then
    close(redis.call('ZRANGE', KEYS[4], 0, 0)[1])
  end
end

local size = tonumber(redis.call('GET', KEYS[2]) or '0')
local last = -1
local top = redis.call('XREVRANGE', KEYS[1], '+', '-', 'COUNT', 1)
if #top > 0 then
  last = tonumber(string.match(top[1][1], '-(%d+)$')) - 1
end
local landed = 0
for i = 9, #ARGV, 2 do
  local n, entry = tonumber(ARGV[i]), ARGV[i + 1]
  if n > last then
    while true do
      local length = redis.call('XLEN', KEYS[1])
      if length == 0 or (length < max_entries and size + #entry <= max_bytes) then
        break
      end
      local oldest = redis.call('XRANGE', KEYS[1], '-', '+', 'COUNT', 1)[1]
      redis.call('XDEL', KEYS[1], oldest[1])
      size = size - #oldest[2][2]
    end
    local added = redis.pcall('XADD', KEYS[1], 'MAXLEN', max_entries, '0-' .. (n + 1), 'e', entry)
    if type(added) ~= 'table' or not added['err'] then
      size = size + #entry
      last = n
      landed = landed + 1
    end
  end
end
if landed > 0 then
  redis.call('PEXPIRE', KEYS[1], idle)
  redis.call('SET', KEYS[2], size, 'PX', idle)
  redis.call('ZADD', KEYS[3], now, stream)
  redis.call('PEXPIRE', KEYS[3], idle)
  redis.call('ZADD', KEYS[4], now, group .. ':' .. stream)
end
return landed
"""
)
"""KEYS: the stream, its byte count, its group's index, every open stream.
ARGV: the prefix, the group, the stream, the four bounds and the idle time
in milliseconds, then each entry's number and bytes."""

READ_SCRIPT = Script(
    _NOW
    + """
local prefix, group, idle = ARGV[1], ARGV[2], tonumber(ARGV[3])
local after = {}
for i = 4, #ARGV, 2 do
  after[ARGV[i]] = tonumber(ARGV[i + 1])
end
local slices = {}
for _, stream in ipairs(redis.call('ZRANGEBYSCORE', KEYS[1], '(' .. (now - idle), '+inf')) do
  local key = prefix .. group .. ':' .. stream
  local first = redis.call('XRANGE', key, '-', '+', 'COUNT', 1)
  if #first > 0 then
    local mark = after[stream] or -1
    local flat = {}
    for _, item in ipairs(redis.call('XRANGE', key, '(0-' .. (mark + 1), '+')) do
      flat[#flat + 1] = item[1]
      flat[#flat + 1] = item[2][2]
    end
    slices[#slices + 1] = {stream, first[1][1], flat}
  end
end
return slices
"""
)
"""KEYS: the group's index. ARGV: the prefix, the group, the idle time in
milliseconds, then each stream the reader names and the last number it saw
of it."""

END_SCRIPT = Script(
    """
redis.call('DEL', KEYS[1], KEYS[2])
redis.call('ZREM', KEYS[3], ARGV[1])
redis.call('ZREM', KEYS[4], ARGV[2])
return 1
"""
)
"""KEYS as the append's. ARGV: the stream, and its member of every open
stream."""


class _Unreachable(Exception):
    """No client: the root has closed."""


class StreamsValkeyImpl(StreamsInterface):
    """A backend that cannot be reached drops the append and reads nothing.
    The client is owned by the infra root, so this impl has no lifecycle of
    its own."""

    def __init__(self, connection: ValkeyConnection) -> None:
        self._connection = connection

    async def append(
        self,
        group: UUID,
        stream: UUID,
        entries: Sequence[tuple[int, bytes]],
        bounds: StreamBounds,
    ) -> None:
        if not entries:
            return
        args: list[TEncodable] = [
            PREFIX,
            str(group),
            str(stream),
            str(bounds.entries),
            str(bounds.bytes),
            str(bounds.streams),
            str(bounds.open),
            str(_millis(bounds.idle)),
        ]
        for n, entry in entries:
            args += [str(n), entry]
        try:
            client = await self._client()
            await client.invoke_script(APPEND_SCRIPT, keys=_keys(group, stream), args=args)
        except GlideError, _Unreachable:
            self._unreachable("append")

    async def read(
        self, group: UUID, after: Mapping[UUID, int], bounds: StreamBounds
    ) -> tuple[StreamSlice, ...]:
        args: list[TEncodable] = [PREFIX, str(group), str(_millis(bounds.idle))]
        for stream, n in after.items():
            args += [str(stream), str(n)]
        try:
            client = await self._client()
            result = await client.invoke_script(READ_SCRIPT, keys=[f"{PREFIX}{group}"], args=args)
            return _slices(result)
        except GlideError, _Unreachable:
            self._unreachable("read")
            return ()

    async def end(self, group: UUID, stream: UUID) -> None:
        try:
            client = await self._client()
            await client.invoke_script(
                END_SCRIPT, keys=_keys(group, stream), args=[str(stream), f"{group}:{stream}"]
            )
        except GlideError, _Unreachable:
            self._unreachable("end")

    def describe(self) -> str:
        return "streams=valkey"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def _client(self) -> GlideClient:
        client = await self._connection.client()
        if client is None:
            raise _Unreachable
        return client

    def _unreachable(self, operation: str) -> None:
        OUTCOMES.labels(subsystem="streams", outcome="unreachable").inc()
        log.warning("streams unreachable on %s; the live view loses it", operation)


def _keys(group: UUID, stream: UUID) -> list[TEncodable]:
    member = f"{PREFIX}{group}:{stream}"
    return [member, f"{member}:bytes", f"{PREFIX}{group}", OPEN]


def _millis(span: timedelta) -> int:
    return max(1, int(span.total_seconds() * 1000))


def _number(entry_id: object) -> int:
    """An entry's number, from its id `0-<n + 1>`."""
    if not isinstance(entry_id, bytes | str):
        raise GlideError(f"an entry id of {entry_id!r}")
    text = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
    try:
        return int(text.rpartition("-")[2]) - 1
    except ValueError:
        raise GlideError(f"an entry id of {entry_id!r}") from None


def _slices(result: object) -> tuple[StreamSlice, ...]:
    """The read script's slices, whatever the driver wrapped them in; a shape
    it never returns is the driver's error."""
    if not isinstance(result, list | tuple):
        raise GlideError(f"the read script returned {result!r}")
    slices: list[StreamSlice] = []
    for row in result:
        if not isinstance(row, list | tuple) or len(row) != 3:
            raise GlideError(f"the read script returned a row {row!r}")
        stream, first, flat = row
        if not isinstance(stream, bytes | str) or not isinstance(flat, list | tuple):
            raise GlideError(f"the read script returned a row {row!r}")
        try:
            name = UUID(stream.decode() if isinstance(stream, bytes) else stream)
        except ValueError:
            raise GlideError(f"the read script returned a stream {stream!r}") from None
        entries: list[tuple[int, bytes]] = []
        for i in range(0, len(flat) - 1, 2):
            entry = flat[i + 1]
            if not isinstance(entry, bytes):
                raise GlideError(f"the read script returned an entry {entry!r}")
            entries.append((_number(flat[i]), entry))
        slices.append(StreamSlice(stream=name, first=_number(first), entries=tuple(entries)))
    return tuple(slices)
