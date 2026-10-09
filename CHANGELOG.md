# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.13.0 (2026-10-09)

The platform's base moves to the engine at v0.12.0, on the guideline's
v0.55.0: leases on a resource, a tenant's cap held at the claim, and the
guideline's shared outage signal, on which a session parks. The claimant
kit times its hold on the guideline's lease clock and guards a resource
with its fence, and the drift audit places a concept by the words that
can state it. Minor: nothing is reversed.

### Added

- From the engine's v0.12.0 and the guideline's v0.55.0, in the
  scaffold: leases on a resource, with the `leases` namespace, its
  `core` tables and hooks, `/v1/leases`, and the Python client's
  `LeaseClock` and `Fence`; a tenant's cap on a shared lane, held at the
  claim; the outage signal, `get_outages()` on the infra root; the
  sweep's standing chores; an integration acting as the member its
  proven address names; a session that waits in line for a resource,
  parked, and parks on the outage signal; ADRs 0086 to 0090, 1024, and
  1025 (#135).
- `LEASE_NOTICE` registers in the platform's kinds registry, both of the
  platform's claims take the tenant cap, and the session runner refuses
  a lane that is no loop lane (#135).

### Changed

- The claimant kit's `LeaseClock` holds the client's `LeaseClock` for
  the hold and keeps only the claim's part: the claim's deadline, a
  renewal at half the shorter of the two, and a wait the platform
  names. Its `deadline`, `refused`, and `out` read the hold, and its
  floor is the client's `MIN_RENEW_SECONDS` (#136).
- A kind that acts on a resource it holds guards it with the client's
  `Fence` (#136).
- `audit-ontology-drift` places a concept in the lowest layer that can
  incorporate it whole, borrowing no noun or concept from a layer above.
  It names the concept's parts by what they do, in any words, and a
  layer's text is evidence, never the test. Whether every instance of a
  layer needs a concept decides at most whether it is `optional` there,
  never its layer, in place of the skill's test by need. The spec
  states the same test (#134).
- The platform shares the guideline's outage signal across its runners,
  where it shared the engine's, and a session that reads a mark parks
  on the provider. The outage report line and the provider-outage
  skill's template name the credential's org (#135).
- The platform's calls of the engine's `member_context` follow its
  rename to `delegated_context` (#135).
- The park table names `grant`, and the API document and the clients'
  types are regenerated (#135).
- The spec, the lenses, and the upgrade skill cite the guideline at
  v0.55.0 and the engine at v0.12.0 (#135).

### Removed

- The claimant kit's own monotonic clock and its `RETRY_FLOOR_SECONDS`:
  the tree holds one lease clock and one fence, the client's (#136).
