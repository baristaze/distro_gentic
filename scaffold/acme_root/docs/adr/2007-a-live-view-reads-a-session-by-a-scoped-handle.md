# ADR 2007: A live view reads a session by a scoped handle beside the realtime channel

**Status**: accepted (2026-10-03)

## Context

The guideline's NET-20 (Apps, Push-First Apps): "One realtime channel
per app, not per feature. Every push rides the same connection as a
typed envelope", and its lens names "a polling endpoint or a poll on a
timer used while the channel is up" a violation.

Watching and Steering, Live Streams: "The live read carries content,
and it is a read, never a push. A viewer is handed a short-lived, scoped
handle, the way a browser app is handed a presigned URL, and reads an
open stream from the part it last saw." The spec records it as one of
its two deviations.

A session's content is many small parts a second while a model writes.
On the channel, every part would ride the tenant's socket to every
viewer of the tenant, each fanned out by the bus, and a slow viewer
would hold the bus's buffer. The channel carries hints and records; the
parts are neither.

## Decision

**The channel carries changes, never content.** What changed rides it as
the guideline's hint and record, a person's taking control, command, and
giving back among them. A part of a stream is neither, and never rides
it.

**Content is read through a handle.** A viewer who may read a session
asks for a handle (`POST /v1/agent-sessions/{id}/live`). The handle is
the grant it names (the session, the viewer, when it expires), signed with HMAC-SHA256 under a key of the platform's, over a
purpose prefix, the way a presigned URL is signed. It lasts five
minutes. A read (`GET /v1/live?handle=`) answers to the handle alone: it
verifies the signature, then the expiry, then reads that session's open
streams and nothing else. A reader names the last part it saw of each
stream, and reads from the one after.

**The stream service is a cache.** It holds a bounded buffer per open
stream (parts, bytes, streams a session, streams overall), and lets go
of the oldest part, never the newest. A reader that missed parts is told
so; the step they add up to holds them once it is stored.

**The watch keeps no table.** Its namespace has no storage: a live part
is a cache, and a person's command by hand is the relay's `exec` item,
attributed to them by an entry in the tenant's event stream written
before it is sent. The checker's one-shape rule is excepted for it.

**The key is one secret of its own,** injected into the API from the
secret store, the same in every API task. A process without one refuses
every live read and says so at start.

## Consequences

- A live view holds two connections: the channel, for what changed,
  and a read of one session's content while it is open on screen.
- A handle is a bearer: whoever holds it reads one session for at most
  five minutes. A member removed from the tenant keeps reading for what
  is left of a handle they hold, and no longer.
- A read costs no database: the signature is the authority, and the
  buffer is in memory.
- A rotated key ends every handle out; a viewer asks for a new one.
- The loop emits into the stream service of its own process. Until a
  carrier brings a runner's parts to the API's, the API's read finds
  nothing open, and the steps hold everything said. The hints for a
  stream opened or completed are not on the channel yet.
