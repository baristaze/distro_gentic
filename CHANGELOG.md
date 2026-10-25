# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.28.0 (2026-10-25)

The platform's base moves to the engine's v0.24.0: a session's title is
sealed at rest, every place the platform shows it opens it, a page at
once, and a revocation leaves it absent. Minor, with the base's
reversal: a read answers a session's title sealed, and what shows it
opens it with `open_titles`. A park alert's row names no title.

### Changed

- The base moves to the engine's v0.24.0, on the guideline's v0.65.0: a
  session's title is sealed under a title key of its own, wrapped under
  the tenant's title key (the engine's ADR 1042), and the loop no longer
  opens again what it wrote. The platform's session views and lists, a
  hand's take and give-back, the assistant's session tools, and a first
  recall open the titles they show; the three session decorators pass
  `open_titles` and the sweep's seal through. A park alert's row names
  its session "A session", and a post on an integration names its
  title, opened. The platform's first core migration, `202610121815`,
  takes the engine's `202610250340` as its parent; a copy whose
  databases applied the release before writes its own migration for
  the title's columns (ADR 0102) (#203).
