# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.33.0 (2026-11-24)

The platform's base is the engine at v0.29.0; a relayed call is woken
as its result lands, measured by its phases, and carries a small
payload inline; a closed pool VM resolves only the names it needs; the
platform's kinds that reach their workspace first prepare it early.
Minor, with one reversal named below.

### Added

- A closed VM of the cloud pool resolves only the names it needs,
  closed at the network: the pool's module puts a DNS Firewall that
  fails closed on a network only the pool uses, allowing
  `allowed_names` alone; an open-egress VM resolves other names
  through public resolvers its egress reaches. ADR 2074 (#231).
- The cloud pool counts its claims by source
  (`acme_cloud_pool_claims_total`), times its restores by archive size
  and a claim's wait until its prepare returns
  (`acme_cloud_pool_claim_wait_seconds`), and the default alarm set
  raises one when the prompt cache's read share of settled model calls
  falls (#232, #241).
- An exec item's time is measured by its phases
  (`acme_exec_relay_phase_seconds`) and its overhead
  (`acme_exec_relay_overhead_seconds`); the host sends its own times
  in the result it already pushes, and pushes again without them if a
  replica refuses them. A core migration keeps the item's claimed time
  and the host's times (#233).
- The software engineer (v9) and analysis (v5) prepare their
  workspace as their run's first model call goes out; a kind kept by
  snapshots that prepares early is refused at load (#241).

### Changed

- The platform's base moves to the engine's v0.29.0: a model call's
  time to its first token, a kind's early prepare (ADR 1048), and the
  tree's dead concurrency column dropped. The platform's first own
  migrations sit above the engine's new ones, so a database migrated
  before the move is made anew (ADR 0102) (#238).
- The runner reads an exec result as it lands, woken over the engine's
  stream-appended topic; its poll is the fallback (#240).
- A file or output of an exec item of 64 KiB or less rides in the item
  or its result, sealed under the session's key; an exec claim carries
  its item's detail; the exec wire is at version 4. The item records
  whether its runner reads inline bytes, so a runner of the release
  before reads its results during a roll. ADR 2076. Reversal: the rule
  that no file and no output rides in an item or its result gives way
  to the bound (#242).

### Fixed

- The spec says once how the runner reaches a VM of the cloud pool:
  through the exec relay; the direct transport serves only a workspace
  on the runner's own machine (#233).
- A change to the cloud pool's launch template reaches the VMs started
  after it: the template moves its default version with each apply
  (#239).
