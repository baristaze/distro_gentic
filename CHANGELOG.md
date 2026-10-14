# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.20.0 (2026-10-14)

A validation's checks run on the environment its session pinned, so
they find what the project's setup installed, and reach nothing. Minor,
with no reversal.

### Fixed

- The fresh executor reads each session's pin. A session pinned to its
  project's environment has its checks run on a new instance of that
  base, never its workspace or a snapshot of it, with no egress, and the
  run's record names the base's image, where they ran on the executor's
  own image and a check that needed the setup's packages failed. Inside
  the wall, a host of the pool makes the instance on the pinned base
  with no egress. A session with no base runs as before (ADR 2062)
  (#170).

### Changed

- The executor's pin reader answers a `Pin`, the session's isolation
  and whether it runs inside the wall, or none for a session of the
  cloud that pinned nothing, and the executor takes a `bases` reader of
  a base's snapshot. The root builds the workspaces' bases once and
  hands them to the tools manager and the executor. A base with setup
  and no `bases` reader refuses the checks before anything runs (#170).
- The spec's A Project's Environment, lens WSP-14, and the workspaces'
  README say a validation's checks run on the environment (#170).
