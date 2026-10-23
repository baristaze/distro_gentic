# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.27.2 (2026-10-23)

A product whose own routers mark its holder's calls passes the
platform's holder-calls test. Patch.

### Fixed

- The holder-calls test left out the routers of the product a case
  serves, but not those the module was imported with, so a product
  whose own routers mark a claimant's route still failed it. It now
  leaves out both, and holds the platform's own routes to its nine
  exactly (#201).
