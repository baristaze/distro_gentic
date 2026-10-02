# Retention

How long a session's content and its shape are kept, under whose key, and
what crosses a customer's wall. This is one of the kinds of thing [Acme
is made of](../../../../README.md).

## What it holds

- **Retention policy**: one per tenant. It says how long what a session
  says is kept, how long its shape is, whether its content may rest at
  all, whether nothing may be kept anywhere (zero retention), and the
  region. A lifetime counts from the session's creation. Left unset, a
  field narrows nothing.
- **Project narrowing**: what one project of the tenant tightens. It
  never loosens: a session of the project takes the tighter of the two,
  field by field.
- **Snapshot**: one per session, taken as it is created. It holds the
  policy the session took, when its content and its shape expire, and
  what the sweep did when they did.
- **Key service**: each tenant's keys live in a key service the tenant
  can revoke, the platform's or one the tenant brought. One that holds
  each session's key, not only the tenant's, can destroy a session's key
  and report it.
- **Crossing**: what crosses the wall (enrollment, claims, stream parts,
  artifacts, results), with the hash its sender declared.

## What can happen

- **Declare a policy.** The tenant's owners and admins write it, with
  each project's narrowing, by a compare-and-set on its version. A
  project that names another region than its tenant's is refused.
- **Snapshot a session.** Taken before the session is written, so no
  session is ever without one. A session spawned or handed over belongs
  to the project of the session it came from. A policy that keeps
  nothing at rest makes the session memory-only before its history
  begins.
- **Sweep.** Once a pass, across tenants:
  - A snapshot takes what its tenant's policy has tightened since it was
    taken. A loosening leaves it as it was.
  - Past its content's life, the session's key is destroyed by its
    tenant's key service, the engine revokes it, and the audit holds the
    destruction as the service reported it. Content at rest that its
    policy no longer lets rest expires at that sweep.
  - Past its shape's life, the session is marked deleted, and the
    engine's purge removes it. That mark is never undone.
- **Revoke the tenant's key.** The tenant does it in its own key service.
  From then on nothing of that tenant's content opens, and every other
  tenant reads and writes as before.
- **Verify a crossing.** The receiver checks the bytes against the hash
  they crossed with before it reads them.
- **Purge.** A deleted tenant's snapshots and policy go with the tenant.

## The rules

- **A snapshot only tightens.** Its policy and its expiries never move
  later.
- **The audit holds the key service's words.** Its entry carries the
  service, the key, the time, and the receipt as the service reported
  them, and a tenant with its own key service finds the same receipt in
  its own log. A service that holds the tenant's key alone reports
  nothing: the engine's revocation is the destruction, and the entry
  says no service reported it.
- **A tenant's key serves that tenant alone.** Its revocation reaches no
  other tenant's content.
- **A crossing that does not verify is refused**, and never read as
  anything.
- **Every policy and snapshot belongs to one org.** Another org that
  names them finds nothing.

<!-- agents-only
The snapshot is taken by `impl/sessions.py`, a decorator over the
engine's sessions manager that the root wires in front of every other
namespace; the sweep marks a session through the engine's own manager.
`impl/keys.py` holds the router the engine's session keys are wired over
(`KeyServiceByTenantImpl`), the tenants' services (`TenantKeysImpl`), and
the local key service (`KeyServiceLocalImpl`), which the root wires in
`local` alone. The pure rules are `rules.py`; the crossing check is
`crossing.py`. ADR 2014 records the decisions.
-->

## How another namespace composes it

The root wires the snapshot in front of the
[agent sessions](../agent_sessions/README.md), and the tenant's key
service under the [privacy](../privacy/README.md) namespace's session
keys. The maintenance worker runs the sweep. Whatever receives something
from across the wall verifies it with `crossing.verified`.
