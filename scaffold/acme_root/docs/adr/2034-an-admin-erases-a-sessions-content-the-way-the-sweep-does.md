# ADR 2034: An admin erases a session's content the way the sweep does

**Status**: accepted (2026-10-04)

## Context

The platform's spec, Data, Retention, and the Wall: step content is
sealed under a key per session, and the keys live in a key service the
tenant can revoke. A retention policy is declared per tenant.

The engine erases a session's content by revoking its key, and keeps
its shape ([ADR 1004](1004-a-sessions-content-is-erased-by-revoking-its-key.md)).
Its revocation asks only the write permission, which every member holds.
The retention sweep revokes a key when the session's content expires.
It also has the tenant's key service destroy the key, and audits the
destruction as that service reported it
([ADR 2014](2014-retention-is-a-snapshot-and-a-destruction-is-the-key-services-report.md)).
Until now only the sweep revoked a key, and only the seed declared a
policy, so a tenant could do neither.

## Decision

**An erasure is the sweep's destruction, run now.** The tenant's owner or
admin erases one session's content through the API. The engine revokes
the key, a session marked deleted included. The tenant's key service
destroys it. The audit holds the destruction, as the service reported
it, under the admin's name. So an erasure on demand proves itself the
way an expiry does.

**It takes the permission to manage members.** The engine's revocation
cannot be undone, and a member's write is too low a bar for it. The
platform's route asks what the policy write asks: the owner and the
admin hold it, and a member or a viewer does not.

**The snapshot records it.** The erasure writes the time and the
service's report into the session's snapshot, so no sweep takes the
session up again or audits it twice. A second erasure answers with the
snapshot as the first left it.

**The policy is written whole on the version read.** A tenant that has
declared no policy reads version 0, which names no record, so its first
write carries no `If-Match`. Each write after names the version it read.
A first write that meets a declared policy is refused, so no write
replaces one its author never read.

**No hard delete on demand.** A session's rows go only by the engine's
purge, one retention after its shape's lifetime
([ADR 1010](1010-a-history-is-purged-by-a-login-of-its-own.md)). A tenant
that wants a session gone erases its content and marks it deleted.

## Consequences

- An erased session takes no content again, as any revoked one: a step
  that says nothing still lands, so a loop under way can end.
- An erasure in a tenant on a key service that holds the tenant's key
  alone is the engine's revocation, and its audit entry says no service
  reported it, as an expiry's does.
- A tenant that wants every session's content gone sooner tightens its
  policy; the next sweep reaches every session it tightens.
