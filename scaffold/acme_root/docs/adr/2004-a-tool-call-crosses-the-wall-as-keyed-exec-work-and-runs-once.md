# ADR 2004: A tool call crosses the wall as keyed exec work and runs once

**Status**: accepted (2026-10-03)

## Context

A session pinned to a tenant's host pool runs its tools on the host that
holds its workspace, inside the tenant's wall, while its loop runs in
the platform's cloud. The engine sees one transport interface, and the
runner picks what is behind it by the session's placement. The host
opens every connection; the platform never calls in, and everything that
crosses the wall is checked against its hash.

## Decision

**Each operation is an item keyed by its call.** The runner's relay
transport sends each operation of a call as an item whose id derives
from the call's key, what the operation does, and how many times the
call did the same before it in the run. A run that resumes the call
meets the same items: it attaches to one still running and reads one
that ended. Only a repeatable item whose last run was stopped or lost
runs again. The engine's file operations carry no call key, so each is
an item keyed by itself: a read, or a whole file written under the run's
epoch.

**The command carries its effect.** The engine's command names no
effect, so the relay could not tell what a repeat may do. The command
takes its tool's effect, and one that names none is never repeated.

**What crosses the queue is ids.** The queue row names the item, the
call, the effect, the isolation, and what it asks of its host's
ceilings. The command, the path, and the bytes are the session's
content, sealed under its key in the relay's record, and the host reads
them through the gateway while it holds the item. The output and the
result are sealed the same way, so revoking the session's key erases
them. A session that keeps no content at rest has none of its commands
relayed.

**An unsafe item is claimed once.** Its queue row takes one attempt, so
the queue's own sweep fails it when its lease runs out, whatever else
runs first. The relay's sweep then ends it `interrupted` and revokes the
host's lease. A repeatable item keeps its row's attempts, and its row
goes back to its host's lane. The relay starts an item at the claim: a
row its item no longer runs under, an unsafe item a claim took before, a
settled item, or a command a lost run sent is settled there and never
reaches a host.

**The first settlement wins.** A result, a stop, and the sweep each
write the item at the version they read. A result for an item already
settled lands nothing.

**A stale writer acts on nothing.** A command, a stop, or a recovery
from a run below the session's writer epoch is refused. A command a lost
run sent, which no host took yet, is refused at its claim, and the
host's own transport fences its workspace by epoch too.

**The control stream is the host's.** The host opens it with its own
credential. It ends after a minute, or with that credential, and the
host opens the next with the credential it holds then. So a credential
the host rotated, or one revoked, is met at an open, as every call meets
it: a stream never shows its credential again, and is never read as its
reuse. A stop is a row first, and its outbox row's push wakes the stream
wherever it is held open; work on the host's lanes wakes it to claim.
The stream reads the rows again on a short timer, since a push is best
effort, and a host that reconnects is told again what it missed.

**The host that holds a workspace is a binding.** The relay keeps which
host holds each session's workspace and where. Trust names that host as
the executor of the session's calls, and until one holds it, a pinned
session's call is refused, never run in the cloud.

**A bare directory waits for its dedicated user.** The host runs a
container per session through the engine's container transport. The
engine's local transport runs as the host's own user, which a bare
directory must not, so the host refuses an item at that mode.

## Consequences

- One relayed operation is one queue row, a claim, a read, and a push:
  slower than a local command, and bounded by the host's claim and the
  runner's wait, which backs off to a second.
- A host that is lost leaves its items running until their lease ends, a
  minute by default, then `interrupted` or back on its lane.
- The same operation twice in one call is two items only within one
  runner process; a run resumed on another runner meets them in order,
  as the engine runs a repeatable call again in order.
- The prepare of a session's workspace on a host, which binds it, and
  the purge of a host's own records, are the workspace work's.
- The engine's transport types gain the command's effect, so the next
  move of the base merges over that field.
- The host imports the engine's transports, isolation, and local
  secrets to run what it holds, which PLC-10's check reads as reaching
  the platform. Its exceptions name this decision: the host dials
  nothing through them and reaches the platform through the client
  alone.
