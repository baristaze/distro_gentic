# ADR 2014: Retention is a snapshot, and a destruction is the key service's report

**Status**: accepted (2026-10-02)

## Context

The platform's spec, Data, Retention, and the Wall: step content is sealed
under a key per session, and the keys live in a key service the tenant
can revoke; a tenant may bring its own. A retention policy is declared
per tenant and narrowed per project. A session takes a snapshot of it
when it is created; tightening reaches existing sessions at the next
sweep, and loosening never reaches back. The sweep revokes the keys of
sessions whose content has expired and purges shape past its own
lifetime, and the audit holds each key destruction as the key service
reported it.

The engine seals each session's content under its own key, wrapped by
the tenant's key service, which keeps no copy: the engine's revocation
empties the one wrapped copy, and that is the destruction
([ADR 1004](1004-a-sessions-content-is-erased-by-revoking-its-key.md)).
Its purge removes a session's rows a retention after the session is
marked deleted
([ADR 1010](1010-a-history-is-purged-by-a-login-of-its-own.md)).

## Decision

**A policy only tightens what it reaches.** One operation, the tighter
of two policies field by field, folds a project's narrowing into its
tenant's policy, and the tenant's policy into a session's snapshot. So a
project never widens its tenant's policy, and a loosening leaves every
snapshot as it was. A region is the one field where neither side is
tighter: a project that names another region than its tenant's is
refused. Lifetimes count from the session's creation.

**The snapshot is taken before the session is written.** A decorator over
the engine's sessions manager takes it first, then lets the engine write
the session, then chooses the engine's memory-only storage when the
policy keeps nothing at rest. So no session exists without a snapshot. A
sealed session whose policy is later tightened to keep nothing at rest
has its content expire at that sweep.

**Each tenant's keys go to its own key service.** The engine's session
keys are wired over a router that sends each call to the tenant's key
service: the platform's, or the one the tenant brought.

**A key service that holds each session's key destroys it and says so.**
Such a service refuses every version of a destroyed key from then on,
and answers with its own report: the service, the key, the time by its
clock, and its receipt. The sweep writes that report into the audit as
it came, and revokes the key through the engine, which reaches a session
marked deleted too while the tenant holds the record of its key. The
content counts as expired only once the engine or the service says the
key is gone. A service that holds the tenant's key alone, as the
engine's do, has nothing of the session to destroy: the engine's
revocation is the destruction, and the audit entry says no service
reported it. In `local`, the root wires the local key service, which
keeps each session's key in its process over infra's.

**The shape's end is the engine's mark.** Past its shape's lifetime, the
sweep marks the session deleted through the engine, and the engine's
purge removes it. The mark the sweep made is never undone.

**What cannot finish waits out of the read.** A session with a loop still
open cannot be marked, and a key service that does not answer destroys
nothing. The sweep records what finished, content never waiting on
shape, and puts the session out of every pass's read until its next
attempt, so no batch fills with sessions that cannot move.

**A deleted tenant is swept without its context.** No context is minted
for it, so the sweep asks its key service to destroy each expired key,
keeps the report on the snapshot, and leaves its sessions to the
tenant's purge.

**What crosses the wall is verified by hash.** A crossing carries its
kind, the SHA-256 its sender declared, and its size, and the receiver
reads the bytes only once both match.

## Consequences

- A session's content lifetime bounds its working life: past it, the
  session takes no content again.
- A session's rows go one engine retention after its shape's lifetime,
  30 days by default. The lifetime is when the session leaves every read.
- Outside `local`, infra's key service holds the tenant's key alone, so
  a destruction there is the engine's and unreported, until a cloud key
  service that holds each session's key is wired behind the router.
- The engine's revocation reaches a session marked deleted while the
  tenant holds the record of its key: the engine's privacy manager
  changes for it, and the next move of the base reconciles it.
- A snapshot outlives its purged session until its tenant's purge, with
  ids and times and no content.
- A tenant brings its own key service before its first session: a key
  opens only under the service that wrapped it.
