# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.19.0 (2026-10-13)

A product's own kinds start from their project's environment, and a
fork of a workspace on a customer's host starts from a copy that host
keeps as the child's. A validation whose work goes to the dead letter
reads refused, and a host's result lands past a renewal of its own
claim. The platform's base moves to the engine at v0.18.0: a member
joins only an org-wide session on their own, a private session's
participants are the ones its creator adds, and a route removes a
participant. Minor, with no reversal.

### Fixed

- A validation session whose work fails on its last attempt reads
  refused, naming the error's class and never its text, where it read
  `queued` for good. The item still fails for good, with its
  dead-letter event and its count, and a refusal that cannot be written
  is logged (#164).
- A host's result lands when a renewal of its own claim moved the
  item's version first: still held by that host under the same claim
  token, it lands on the version the renewal left; settled, or held by
  another claim, it is refused as before. The host tests pace every
  poll of a host under its write budget (#166).
- From the engine's v0.18.0, in the scaffold: a self-join takes an
  org-wide session only, `manage_sessions` included, and only its
  creator adds a participant to a private session (#167).

### Added

- `ProductKinds.environments` names, by name and version, the product's
  own agent kinds whose workspace starts from the environment its
  session's project names. The root hands the workspaces the platform's
  `ENVIRONMENT_KINDS` and the product's together, and a pair that is no
  agent kind of the product's is refused at boot. ADR 2051 and the
  agent-kind skill name the field (#163).
- A spawn that forks a workspace a customer's host holds asks that host,
  through the relay, to snapshot it at the spawn. The host keeps the
  copy in the child's folder (`kept_for` on the `snapshot` item), so the
  parent's erase never reaches it, and the child's first prepare
  restores it on a host of the pool. The parent keeps no copy. A
  memory-only parent, no live holder, or a host that takes no snapshot
  refuses the fork before a slot or a child (ADR 2061) (#165).
- From the engine's v0.18.0, in the scaffold:
  `DELETE /v1/agent-sessions/{session_id}/participants/{user_id}`
  removes a participant. The platform's project, retention, and
  workspace decorators pass the removal on as they pass an add, and the
  TypeScript client's schema carries the route (#167).

### Changed

- The tools manager asks the platform for a fork point first, else
  takes the engine's: `ToolsManagerImpl` takes an optional
  `fork_points`, and without one every fork point is the engine's, as
  before (#165).
- The portal's client says who joins, and its test transport refuses a
  self-join of a private session as the API does (#167).
- The lenses cite the engine's lens index at v0.18.0 (#167).
