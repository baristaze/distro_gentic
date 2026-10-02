# ADR 2003: A host enrolls once and holds its owner's ceilings on its own disk

**Status**: accepted (2026-10-02)

## Context

A workspace host runs a tenant's work inside the tenant's wall. It is a
client of the gateway, like the CLI. It enrolls once with its tenant's
enrollment token and gets a short-lived, rotating credential of a kind
and prefix of its own. It is handed only the work pinned to its pool, by
its identity. It advertises only what it probed, a claim below the
supported version is refused, and it holds limits its owner sets that
the platform cannot raise.

The gateway already decides by a credential's prefix which transition
accepts it. The work queue already has a lane per pool and per host, and
placement already claims for a host from the lanes its identity names.

## Decision

**Two credentials, each its own kind.** An enrollment token (`hen_`) is
issued by an owner or an admin for one pool. It enrolls every host that
presents it for a day, until it is revoked. A host credential (`hst_`)
is the host's alone. It lives an hour, and the host rotates it at half
its life. A credential rotates once. The one it rotates away from still
works for a minute, so a call in flight with it lands, and any older one
ends. A second rotation of a credential means two machines hold it, and
neither can be told from the other: it is refused, and the host and
every credential it holds are revoked, so its owner sees it. Both kinds
are kept as digests, unique across tenants, since a host's call names no
tenant. The tenant's transitions know neither prefix, and a host's
routes accept only `hst_`.

**The identity is the credential's.** A host's claim states only the
version of `exec` work it reads. The tenant, the pool, and the host come
from the credential, and placement claims from the lanes they name.

**A floor per wire type.** `exec` and `station` carry a version, and the
platform hands work only to a machine at or above each type's floor. A
host below it is refused at its claim and its enrollment, and does not
count as online.

**A pinned session waits.** A principal places a session on a pool or in
the cloud, and nothing else moves it. Its placement reads `waiting`
while no host of its pool is online. The trust swimlane reads it as
inside the wall, and a call of it that no host is named to run is
refused, never run on the runner instead.

**The ceilings live on the host.** Its owner writes them in a file on the
host, which the host reads at startup and holds frozen. No answer of the
platform carries them, and no item changes them. Every item is read as
an ask: its project, its isolation, its egress, the paths it reads, and
whether it is a person's command. A field the item leaves out is read as
the widest ask. The host refuses an item past any ceiling, or at a mode
it did not probe, before anything runs.

## Consequences

- A host holds logic, as a station's daemon does: its probes and its
  owner's ceilings decide what runs. That departs from the guideline's
  DEL-01 for the same reason the daemon does. The guard nearest the
  machine must hold when the platform is wrong.
- A host offline for more than an hour has no live credential, and its
  owner enrolls it again with a new token.
- A copy of a credential rotates beside its host only once before both
  end, so a credential taken from a disk is worth an hour at most. A host
  whose answer to a rotation is lost holds only the credential it rotated
  away from, and its next rotation ends it: its owner enrolls it again.
- A compromised control plane can still describe an item wrongly, such
  as its project. The host runs an item at no more than it asked, so a
  wrong isolation or egress widens nothing.
- Today's payloads name where an item runs and nothing of what it asks,
  so a host refuses every command and every workspace it would prepare
  until their producers name their asks.
- The engine's storage root, the managers' root, the sweep's purge list,
  and the signature tests' registries gain the hosts, so the next move
  of the base merges over each.
