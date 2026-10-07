# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.7.0 (2026-10-07)

The platform's base is the engine at v0.7.0, on the guideline at
v0.52.0: a copy's local stack runs each database role on its own
Postgres, and a job runs the release before on a branch's schema. The
portal's image builds, and CI builds each of a copy's images. Minor: the
base move adds a CI gate and a migrate command, and nothing is reversed.

### Changed

- The base moves to the engine at v0.7.0. A copy's local stack runs
  `postgres-core`, `postgres-activity`, `postgres-queue`, and
  `postgres-admin`, each with its own port and volume, and `migrate
  ensure-logins` runs once per database; the cloud keeps one instance.
  The platform's Postgres band in `.env.example` is 55452 to 55455. A
  copy renames `<NAME>_POSTGRES_PORT` to `<NAME>_POSTGRES_CORE_PORT`, and
  a second checkout repoints every database URL.

### Added

- `release-before`, from the guideline: a job in a copy's CI that runs
  the integration suite of each release before on a branch's migrated
  schema, with `make release-before`, `migrate stamp`, and
  `scripts/release_before_deselect.txt`. It leaves the live tests and the
  benchmarks out. The platform's CI runs it on a copy's branch that adds
  a migration, in a job of its own beside the copy jobs.
- The platform's CI has an `images` job: it renders a copy and builds
  each image the copy's own CI builds (api, maintenance, session-runner,
  portal), nothing pushed.

### Fixed

- The portal's image builds: its Dockerfile copies
  `deployment/cloud/environments.json`, which its Vite config imports.
