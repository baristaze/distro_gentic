# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.22.0 (2026-10-15)

A product's service reaches the platform's live reads and its own
stream kinds through the product seams, and a performance issue in a
hosted command's output is fixed. Minor; a product's service factory
takes one more argument.

### Fixed

- A performance issue in a hosted command's output (#177).

### Changed

- Breaking: a product's service factory takes `ProductLive`, the watch
  and the streams of the product's own kinds, as its third argument, so
  a product service opens a live read or writes its own stream kind
  from its seam files alone (ADR 2064) (#176).
- `distro-upgrade-scaffold`: a product's wiring stays in the product
  seams through a base move, and a seam file the platform gives takes
  the render's (#176).
