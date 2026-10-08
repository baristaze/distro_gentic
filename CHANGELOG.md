# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.12.0 (2026-10-08)

The platform's base moves to the engine at v0.11.0, which carries the
guideline's v0.53.0: a feature flag is an infra capability behind
`FlagsInterface`, with its provider chosen at boot, and the portal reads
its session's flags as one snapshot from `GET /v1/flags`. Minor: the
base carries the guideline's one reversal, DEL-22; the platform's own
rules reverse nothing.

### Added

- From the engine's v0.11.0 and the guideline's v0.53.0, in the
  scaffold: `FlagsInterface` in infra beside the engine's keys and
  streams; `ACME_FLAGS_BACKEND` (`memory`, `launchdarkly` through
  OpenFeature, or `none`); `media-uploads` gating a new upload with
  `403 feature_off`; `GET /v1/flags` with its `ETag`; ADR 0085 (#130).
- The portal reads its flags snapshot in its per-org shell, and a
  switch drops it with the old tenant's caches; Settings, General says
  when new uploads are paused (#130).

### Changed

- The spec, the lenses, and the upgrade skill cite the guideline at
  v0.53.0 and the engine at v0.11.0, and the clients are regenerated
  (#130).
- From the guideline: DEL-22, reversed. A vendor's flag SDK outside the
  infra flags package is the violation, and DEL-52 keeps one out of a
  browser app (#130).
