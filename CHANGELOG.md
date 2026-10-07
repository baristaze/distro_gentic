# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.8.0 (2026-10-07)

A product asks, from its own checkout, which concept sits in the wrong
layer of its adoption chain; the spec takes its new title; and the
platform's base is the engine at v0.7.1. Minor: the scaffold gains an
audit skill, and nothing is reversed.

### Added

- `audit-ontology-drift`, a skill in the scaffold that a product runs
  from its own checkout. It walks the adoption chain down its renders'
  trailers, lists each layer by its title (Software Design and
  Architecture Guidelines; An Engine for Long-Running Agents; A Spec
  for a Closed-loop, Cloud-first, Distributed Agentic Platform; and the
  product's own), reads each layer at the commit the product holds, and
  judges each concept a layer adds for drift in either direction. It
  writes its report under `~/Downloads` and changes nothing in the
  checkout. The spec says the gates hold the layers consistent with
  each other and cannot say whether a concept belongs to a layer: that
  is the question this audit asks.

### Changed

- The spec is titled "A Spec for a Closed-loop, Cloud-first,
  Distributed Agentic Platform", and its subtitle names it a platform
  spec for closed-loop agent fleets.
- The base moves to the engine at v0.7.1, on the guideline's v0.52.1:
  a copy's local Postgres reads healthy only once it takes a connection
  over TCP (`infra/tests/test_local_postgres.py` holds it), and a copy
  that names a test in its release-before deselect file keeps its unit
  gate. The spec and the lenses cite the guideline at v0.52.1 and the
  engine at v0.7.1.
