# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.14.0 (2026-10-09)

The platform's base moves to the engine at v0.13.0, on the guideline's
v0.57.0: a kind's own lane in the relay, a tenant's own cap on a lane, a
lease its job's worker keeps, and a job's call that waits in line for
its grant. The platform's fair share becomes the guideline's caps, held
at the claim: a tier's share is its lane's cap, and an operator's cap on
one tenant holds in its place. Minor, with one reversal: under PLC-02, a
loop over its tenant's share is passed over at the claim, no longer
claimed and handed back after a delay.

### Added

- From the engine's v0.13.0 and the guideline's v0.57.0, in the
  scaffold: a kind's own lane in the relay (`WORK_LANES`,
  `relayed_lane`); a tenant's own cap on a lane (`queue.tenant_caps`)
  and its operator route; a lease kept by the worker that runs its job;
  a job tool that waits in line for its grant; ADRs 0092 to 0094 and
  1026 (#138).
- A tier's lane passes its tier's share to the guideline's claim as its
  cap (`PlacementOptions.tier_shares`, and `default_share` for a tier
  that names none), so a tenant at its share is passed over and spends
  no attempt (ADR 2048, #139).
- The share route, `PUT /v1/admin/orgs/<org_id>/share`, writes its
  optional `concurrency` as the tenant's own cap on its loop lane,
  through the queue's operator plane. A cap on a lane the tenant leaves
  stays with its queued loops there (#139).
- A core migration, `202610042105`, defaults `fair_shares.concurrency`
  and adds `cap_carried`. The sweep carries each row's concurrency into
  the tenant's own cap once, unless a cap is already there (#139).

### Changed

- The relay lands an item on `relayed_lane`, which reads the platform's
  kind names, and placement still answers a loop's tier lane at the
  insert. The loop lanes' stem is the kinds registry's loop lane, so the
  two cannot drift (#138).
- The platform's `queue` migration `202610035702` revises the
  guideline's new head, `202609280003` (#138).
- `fair_shares` holds a tenant's tier and its own lane. Its
  `concurrency`, `cap_carried`, and the carry step stay until a later
  release drops them (#139).
- A session's standing reads the cap of its loop's lane and the
  tenant's claims there alone, and `ops-session-stuck` says whether that
  cap is the tenant's own or its tier's share (#139).
- PLC-02, reversed: a claimed loop over its tenant's limit is no longer
  handed back to its lane with a delay. The guideline's claim passes
  over a tenant at its cap, and a limit of the platform's own beside
  those caps is the violation (#139).
- The spec's Fair Share, ADR 2002, and `distro-scaffold-runner` state
  the caps, and MNY-08 names the guideline's outage signal (#139).
- The API document and the clients' types are regenerated, and the
  object model's check names the unlock a granted job's park carries
  (#138, #139).
- The spec, the lenses, and the upgrade skill cite the guideline at
  v0.57.0 and the engine at v0.13.0 (#138).

### Removed

- The session runner's share guard, `FairShareGuardImpl`, which claimed
  a loop over its tenant's share and handed it back (#139).
