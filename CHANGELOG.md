# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.10.0 (2026-10-07)

A product's claimant runs on the platform's claimant kit, and the base
is the engine at v0.9.0, which holds the loop's seams the platform had
built in the engine's files. Minor: the kit is new, and the platform's
copy of the engine carries fewer edits; nothing is reversed.

### Added

- The claimant kit, `acme.client.claimant` in the Python client: a
  claimant of any registered kind enrolls once, keeps an owner-only
  credential written atomically and rotated at half its life, claims,
  renews, and reports through `/claimants/...`, backs off, and keeps a
  journal of the reports not yet sent. A report is held to its shape
  before it is kept. The host runs on it and keeps its probes, ceilings,
  and relay. `deployment/claimant/install.sh` installs any kind under
  its own unit, user, and settings prefix, with a drop-in hook per
  kind; the host's installer passes the host's names (ADR 2046, #120).
- A claude.ai run of `browser-judge-distro` on 2026-10-07, at sizes
  `m, m` on v0.9.0: 73 (#119).

### Changed

- The base moves to the engine at v0.9.0 (#122). The platform's copy of
  the engine's files no longer carries the per-call credential,
  `GateParked`, the sink's `opened` and `completed`, or ADR 1009's
  paragraph, which the base holds; the tenant-key store, the billing
  gate, the live view, and the models layer's own fields stay the
  platform's. Every workspace refusal on the platform's prepare path
  says it clears, so a session waiting on placement parks on the
  resource and asks again (ADR 2005). The engine's account mode arrives,
  refused outside `local`. The lenses cite the engine at v0.9.0.
- `distro-benchmark-browser` polls a site for up to three hours, 180
  polls, and the schema's `polls` follows (#121).
