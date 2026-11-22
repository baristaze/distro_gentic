# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.31.0 (2026-11-22)

The platform's base is the engine at v0.27.0, so a session whose pinned
workspace can never be held where it runs ends before any model call,
and its end names the cause. Minor.

### Changed

- The platform's base moves to the engine's v0.27.0, through v0.26.1;
  the move's render is on the `scaffold` branch (#226).
  - The platform's loop hook refuses a pinned workspace that can never
    be held where the session runs: the session ends errored before any
    model call, naming the refusal's cause, where before the cause
    reached only the log.
  - The session runner completes a loop item for a kind whose loop runs
    in the request that asks it, without running it, so no worker takes
    up a loop its request bounds (the engine's v0.26.1).
