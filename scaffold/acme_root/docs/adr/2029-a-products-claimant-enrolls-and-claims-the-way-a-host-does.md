# ADR 2029: A product's claimant enrolls and claims the way a host does

**Status**: accepted (2026-10-03)

## Context

A product registers its own claimant kind (ADR 2025), and placement
claims for it only the kinds that name it back, from the lanes its
identity names, never across a tenant's wall. That rule holds only for
an identity the platform resolved. The only path from a credential to a
claimant is the host's, with the host's kind built in, so without a path
of the platform's own a product builds its claimant's enrollment, its
rotating credential, its routes, and the mapping from a credential to a
claimant itself, and the tenant wall of every claim rests on that code.

A host's path already holds what a claimant needs (ADR 2003): a token a
tenant issues for one pool, a short-lived credential of a kind and a
prefix of its own that rotates once, the tenant and the pool read off
the credential, and a revocation that takes effect at the next call.

## Decision

**The host's path serves every registered claimant kind, and the host
is one of them.**

- **A claimant kind registers its credential's prefix.** The registry
  refuses a prefix registered twice, and one another credential of the
  platform carries (a person's, an operator's, an enrollment token's, a
  push token's). So a prefix names one kind, and a tenant route refuses
  every claimant's credential.
- **An enrollment token names its kind.** An owner or an admin issues it
  for one pool and one registered kind, a host unless the call names
  another. The kind, the tenant, and the pool are the token's; the
  claimant names none of them.
- **The identity is the credential's.** A claimant's credential resolves
  to its kind, its id, its tenant, and its pool, and the kind must be
  its prefix's. Nothing in its call adds to it.
- **One lifecycle.** A product's claimant rotates, is revoked, and is
  revoked for a reused credential exactly as a host is, through the same
  code.
- **Each kind has its own calls.** A host enrolls with what it probed
  and claims with the version of `exec` work it reads, at `/hosts/...`.
  A product's claimant enrolls with its name, and claims, reads, renews,
  and reports the item it holds under its claim token, at
  `/claimants/...`. Neither credential opens the other's calls.

## Consequences

- One migration: an enrollment token and an enrolled row carry their
  kind, defaulting to the host's for the rows that exist and for the
  previous release's writes. What a host advertised and the version it
  reads are a host's alone, so those columns are nullable.
- A product's claimant is a row of `hosts`. Every read of hosts (a
  pool's, the gauge's, a placement's count of hosts online) takes the
  host kind alone, so a product's claimant never counts as a host.
- A product's claimant states no version: the platform reads no wire
  type of a product's, so a floor on one is the product's.
- `ClaimantKindSpec` takes a `prefix`. ADR 2025's consequence that a
  product's own route resolves its claimant's credential, and that the
  platform issues none of its kind, no longer holds.
- `distro-scaffold-work-kind` names the prefix, and the product's
  claimant calls the platform's routes.
