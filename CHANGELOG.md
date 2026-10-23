# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.27.1 (2026-10-23)

A product marks its own holder's calls without failing the platform's
test. Patch.

### Fixed

- The scaffold's holder-calls test read every marked route under a
  host's and a claimant's own paths, the product's routers included, so
  a product that marked its own claimant's renewal failed it. It now
  leaves out the routes the product's routers serve and holds the
  platform's own to its nine exactly (#199).
