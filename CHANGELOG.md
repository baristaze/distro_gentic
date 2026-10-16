# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.23.0 (2026-10-16)

An unused table leaves the core schema. Minor; a copy's next base move
takes a migration that drops it.

### Removed

- `core.exec_parts`: nothing reads or writes it, and a core migration
  drops it (#179).
