# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.26.0 (2026-10-22)

The platform's base moves to the engine's v0.22.0, on the guideline's
v0.64.0: a copy's gates take less time, its suites on every core and side
by side. Minor.

### Changed

- The base moves to the engine's v0.22.0. A copy's `make test-unit` runs
  on one worker per core and ends on its ten slowest tests (ADR 0105: a
  unit test holds nothing another can reach, its id fixed at
  collection); its CI starts the integration, telemetry, and image jobs
  beside the fast gate; the integration wipe empties only the tables
  written since the last one; `make openapi` cuts the schema in linear
  time; and arch-check is pinned at v0.64.0 (#191).
- This repository's CI runs each copy's fast gate and integration suite
  as jobs of their own, side by side (#189).

### Fixed

- The unit suite holds no wall-clock bound a loaded runner can miss: the
  evidence rules' refused runs carry a fixed time, so their ids are the
  same in every collection; the exec relay's stop test holds the stop
  against the command's own run; and the watch test's bound on writes
  grows with the time its parts took (#190).
