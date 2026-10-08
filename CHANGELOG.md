# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.12.1 (2026-10-08)

The session runner's access test names the flags' SDK key, which 0.12.0
injects into the runner and its own test did not list, so a copy's
Terraform tests pass again. Patch: nothing is reversed.

### Fixed

- The staging root's `session_runner_access` test lists
  `ACME_LAUNCHDARKLY_SDK_KEY` among the runner's injected secrets: the
  infra root the runner boots refuses the `launchdarkly` backend
  without it. The test still refuses a purge login and the identity
  provider's key in the runner (#132).
- The comment beside the runner's secrets in the environment module,
  and ADR 2026, name the key among what its execution role injects
  (#132).
