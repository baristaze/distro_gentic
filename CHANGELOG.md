# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.3.0 (2026-10-04)

A product declares its own ceilings and automation actions, a member
sets budgets through the API, and the platform builds on the engine at
v0.4.0. Minor: rules are added, and one rule of the guideline is
reversed.

### Fixed

- A host's control stream holds no read slot of admission, so a fleet
  of connected hosts no longer takes every read on its replica (#66).
- The audit opens on the org's newest events: `GET /v1/events/recent`
  pages back from the head, and the portal loads older pages down to
  the floor (#69).
- The repository's `CLAUDE.md` lives under `.claude/`, so the plugin
  validates with `--strict`, and CI pins the Claude Code that checks it
  (#65).

### Added

- A product declares the ceilings of its own tool classes beside its
  kinds, and the boot refuses a ceiling of a platform class, of a class
  the product does not declare, or of a class a platform ceiling
  already names (#67).
- A product adds its own kind of automation action beside starting and
  messaging a session: its check says when the work ended, and the run
  stays open until then and closes `succeeded` or `failed`. A kind no
  product declares, or params off its shape, is refused when the
  automation is written (#71).
- A member who governs members sets a budget over a person, a project,
  or the tenant, in any window, in reference cost or native tokens,
  through `POST /v1/budgets`, and anyone who reads lists them; a scope
  no model call is charged to is refused (#72).

### Changed

- The scaffold base moves to the engine at v0.4.0, and through it the
  guideline at v0.50.0: a deleted tenant's purge takes each session's
  workspace and transport records through the platform's tools wrapper
  before it marks the tenant purged, a recovered job call runs once, a
  migration waits for a lock only briefly, an outbound breadcrumb keeps
  no URL path, and the portal's error reports keep no query. The spec
  and the lenses cite the guideline at v0.50.0 and the engine's lenses
  at v0.4.0 (#73).
- Reversed: the guideline's NET-26 no longer asks a statement deadline
  of a migration's connection; a migration carries a bounded lock wait
  instead (#73).

### Removed

- The workspace row's old single `notice` column, and the default on
  its `notices` list (#68).
- The validation sessions' old station columns (`lab_id`,
  `check_version`, `parameters`); a session's project and commit turn
  not null, and a row with neither, which no release could read, is
  deleted (#70).
