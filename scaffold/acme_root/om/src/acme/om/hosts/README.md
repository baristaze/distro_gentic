# Hosts

The machines a tenant runs its work on inside its own wall, and where each
session runs. A workspace host is the platform's; a product's claimant
enrolls and calls the same way, as a kind of its own
([placement](../placement/README.md)). This is one of the kinds of thing
[Acme is made of](../../../../README.md).

## What it holds

- **A host pool**: one or more hosts inside a tenant's wall that share
  labels, in a region.
- **An enrollment token**: issued by an owner or an admin for one pool
  and one claimant kind, a host unless it names a product's. Every
  claimant of that kind that presents it before it expires (a day) or is
  revoked enrolls into that pool. Only its digest is kept.
- **A host**: one enrolled machine. It names its pool, the token it
  enrolled with, what it advertised at its last call, the version of
  `exec` work it reads, and when it last called.
- **A claimant of a product's kind**: one enrolled machine of that kind,
  in its pool, with its name and when it last called. It advertises
  nothing and reads no `exec` work, so it is none of the pool's hosts.
- **A claimant's credential**: its own, under its kind's prefix (`hst_`
  for a host), which no other credential has. It lives an hour, and the
  claimant rotates it at half its life. Only its digest is kept.
- **A session's placement**: the cloud, or one of the tenant's pools. A
  session no principal placed runs in the cloud.

## What can happen

- **Make a pool, issue a token.** An owner or an admin, for a registered
  claimant kind.
- **Enroll.** A host presents a token of the host kind, once, with its
  name and what it probed, and gets its credential. The tenant and the
  pool are the token's; the host names neither. A product's claimant
  presents a token of its kind with its name alone, and its kind is the
  token's too.
- **Rotate.** A claimant trades its credential for the next one. The one it
  called with still works for a minute, so a call in flight with it
  lands. A credential rotates once. A second rotation of it, or a call
  with it past its grace, means two machines hold the claimant's
  identity, and revokes it and every credential it holds, for its owner
  to see and to enroll it again.
- **Beat.** A host says it is online, and what it probed. The platform
  keeps what it is told and adds nothing to it.
- **Claim.** A host asks for work, stating the version of `exec` work it
  reads. A version below the floor is refused before anything is
  claimed. Otherwise placement claims for it, from its own lane and its
  pool's, read off its identity. A product's claimant claims with nothing
  in its call, and reads, renews, and reports the item it holds under its
  claim token, each through placement and read off its identity.
- **Revoke.** An owner or an admin ends a token, or a claimant and every
  credential it holds, at once.
- **Place a session.** A principal pins it to a pool, or moves it back to
  the cloud. Nothing else moves it. A sub-agent runs where its tree's
  root runs, so only a root is placed.
- **Purge.** A tenant deleted past its retention loses all of it.

## The rules

- **A claimant is no person.** Its credential opens its own kind's calls
  and nothing else, and no other credential opens them: a host's opens a
  host's, and a product's claimant's opens the claimant calls. Whatever a
  claimant writes names the person who issued its token.
- **Its identity is its credential's.** A claim takes the claimant, its
  kind, its tenant, and its pool from the credential, never from the
  call. A prefix names one kind: the registry refuses a prefix twice, or
  one another credential carries.
- **A stale host is handed nothing.** `exec` is a public wire type with
  a version and a floor (`rules.WIRE_FLOOR`). A host
  below the floor is refused at its claim and its enrollment, and does
  not count as online.
- **A pinned session waits, and says so.** Its placement reads `waiting`
  while no host of its pool is online, and it stays pinned however long
  that lasts.
- **Every row belongs to one org**, and goes with the org. A token's and
  a credential's digest is unique across orgs, since it is how a
  claimant's call finds its org.

<!-- agents-only
Trust's `PlacementInterface` (inside the wall, and the executor of a
session's next call) is answered here, by `impl/placement.PlacementHostsImpl`,
which the session runner wires. A pinned session's call is refused
(`PinnedToHosts`, a `NotAuthorized` the loop answers as denied) until the
relay names the host that holds its workspace. The
manager methods a host calls take `RequestContext` and a `HostIdentity`
that only `authenticate` builds, at the gateway (`gateway/hosts.py`); a
product's claimant's take a `ClaimantIdentity` that only
`authenticate_claimant` builds. The kinds and their prefixes are the one
registry the root built (`placement.kinds.ClaimantKinds`), reserving the
platform's other credentials' prefixes (`root.PLATFORM_PREFIXES`). A
claimant of a product's kind is a row of `hosts` with its kind, and every
read of hosts (the pool's, the gauge's, `placement_of`'s) takes the host
kind alone (ADR 2029).
What a host reads of an item it claims is the owner's ceilings' business,
on the host (`apps/host`, ADR 2003).
-->

## How another namespace composes it

The gateway resolves a host's credential with `authenticate` and calls
`claim`, which hands placement a claimant built from that identity. It
resolves a product's claimant's with `authenticate_claimant` and calls
`claim_as`, `held_as`, `extend_as`, and `report_as`, which hand placement
the same. A
producer of a session's workspace reads the session's pool from
`placement_of`; a session with no pool runs in the cloud.
