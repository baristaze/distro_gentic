# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.24.0 (2026-10-20)

The platform's base moves to the engine's v0.20.0, with the guideline's
v0.62.0, whose retry waits and periodic loops come from one shared
package, and the platform's own waits take theirs from it. A host
reconnects on a jittered wait and exits 7 when refused, session pages
stay current, and a workspace prepare no longer outlasts its claim.
Minor: the base's folder tree names `libs/`, and a refused host's exit
code moves from 1 to 7.

### Added

- From the base: `libs/timing` (`acme-timing`), with `RetryPolicy`,
  `Retries`, `retry_after`, and `Every`; a model call that never left
  releases its hold; and the engine's demo (#184).

### Changed

- The base moves to the engine's v0.20.0 and the guideline's v0.62.0,
  their retry waits on `RetryPolicy` and their periodic loops on
  `Every`. The runner image copies `libs/timing`, and the spec and
  lenses cite both releases (#184).
- The claimant kit's `Backoff` gives way to `acme.timing`: the claimant,
  the host agent, and the host's control stream count their failures
  with `Retries`; the relay's wait, VM enrollment, and the six polls
  toward a deadline take their waits from a `RetryPolicy`; and the
  host's keep-alive and the relay's renewal run on `Every`, start to
  start. `distro-check`'s PLC-10 lets a host import `acme.timing`
  beside the client (#185).
- A host that the platform refuses exits 7, so its units restart one
  that crashes with 1 (#182).

### Fixed

- A host reopens its control stream on a jittered wait, honors a 429's
  wait, and starts over on a message; VM enrollment's retry is jittered
  too. The API spaces control reads at least a second apart (#182).
- The portal's replay keeps the last push of each session, and an
  automation's run with no session yet is closed as lost a while after
  it started, not after it was queued (#181).
- A host pulls an absent image beside a workspace's prepare and answers
  a refusal that clears after 20 s, and an exec item's lease is renewed
  while its workspace is prepared (#183).
