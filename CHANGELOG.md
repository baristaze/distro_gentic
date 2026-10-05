# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.4.0 (2026-10-04)

A member starts a validation session, erases a session's content, writes
the retention policy, and reads usage through the API; a product declares
its CLI command groups and checks the writer of its automation actions;
and the platform builds on the engine at v0.5.0. Minor: routes and an
abstract hook are added, an action is reversed, and a product's kinds
change on upgrade: each declares `check_writer`, and a kind a product
spawns names a share.

### Fixed

- A hidden suite's run judges the head by the base's verdict code: the
  suite's own files come from the suite's source, every other path the
  scenario forbids from the scenario's base (or is left out where the
  base has none), and the rest from the head. A head that rewrites what
  scores the suite no longer has its hidden cases read by its own copy
  (#79).
- A host's or claimant's enrollment token enrolls only while its issuer
  still manages members (#84).
- A question's notification row keeps the unquoted text, and only the
  integration post quotes it; a session's purge deletes its
  notifications, and an index on `core.notifications` by session comes
  with it (#84).
- A host that reaches a cloud metadata service at start takes no item
  asking for open egress, and the deployment README blocks the metadata
  address on TCP 80 by user (#84).
- Pool membership is read per host, and host lists skip revoked rows, so
  a pool past its first thousand rows still binds its newer hosts (#84).
- A wire failure on a command's last output part keeps its result (#84).
- Revoking a host ends its queued work and settles its commands as
  interrupted, and a command sent after a revoke is refused; stopping a
  queued command and purging a session end their queue rows (#84).
- A validation session runs a rated check's declared trials and passes
  only on the whole batch (#85).
- A session parked on a person past its shape's life is cancelled, then
  marked (#85).
- A deleted tenant's matrix pins and fill choices go before the tenant
  is marked purged (#85).
- A snapshot push the forge refuses waits for the session's next loop
  (#85).

### Added

- A release moves the `release` branch from `main`, tags it, and
  publishes the GitHub release behind one approval step
  (`.github/workflows/release.yml` and `human-approval.yml`). The step
  refuses an environment with no required-reviewers rule, which a
  private repository has only under GitHub Enterprise, so there a
  release is tagged and published by hand (#76).
- A product declares its CLI command groups in `product_commands.py`,
  and the CLI mounts them after its own. A name the CLI already holds, a
  group's or a command's, or one declared twice, is refused when the CLI
  starts (#77).
- A product's automation action checks its writer: the abstract
  `AutomationActionInterface.check_writer(ctx, params, runs_as)` runs
  when an enabled automation of that kind is created or edited, under
  the writer's context and with whom the automation runs as. A refusal
  answers 403 with its reason, so an automation its firings would refuse
  is never saved. Every product kind declares it on upgrade; a kind with
  no rule of its own returns. ADR 2032 records it (#78).
- A member who may write starts a validation session for a project's
  head and base through `POST /v1/validation-sessions` under an
  `Idempotency-Key` (one key, one session, run once), and a member who
  may read gets it through `GET /v1/validation-sessions/{id}`: queued,
  then finished with `passed`, its reason, and the run. A run passes
  only at the grade the project's policy asks for the check, so a double
  or an unavailable device reads `passed: false`. Another tenant's
  project is not found, and a check the policy does not declare is
  refused (#80).
- An owner or an admin erases one session's content through
  `POST /v1/retention/sessions/{id}/erase`, the way the sweep expires
  it: its shape stays, and the snapshot records it so no sweep repeats
  it. They read and write the tenant's retention policy, and a project's
  narrowing, through `GET` and `PUT /v1/retention/policy` on `If-Match`;
  a lifetime longer than a century is refused with 422. A member gets
  403 and another tenant 404. ADR 2034 records it (#82).
- `GET /v1/usage` reads billing's spend, in the tenant's windows (#85).

### Changed

- The spec's title is A Platform for Closed-Loop Agent Fleets, with the
  code name and the qualifiers in the subtitle, and the README links
  each part it names (#75).
- The platform's 26 ADRs drop what restated a spec section or the
  guideline, narration of a former state, and consequences that only
  restated the decision. Every decision, bound, identifier, and near
  miss stays, and no file is renamed (#81).
- The scaffold base moves to the engine at v0.5.0, and through it the
  guideline at v0.51.0: every billed model call writes a usage record
  with no content, and a read operator reads a session's records with
  per-loop and per-session rollups; a child whose loop ends writes its
  report into its parent's inbox; each wall is checked at the call; a
  session spawned or handed over by one that holds private data holds it
  too; the spend skills `ops-loop-spend` and `ops-session-spend` come
  in, `audit-model-spend` is the engine's, and the platform's matrix
  spend audit is `audit-matrix-spend`; a production run asks a person
  once, and a reusable approval step and a branch-ruleset script come
  in; billing keeps its money ledger and never lets it keep a tenant
  from being marked purged; the worker and the API carry the platform's
  tool catalog and the comment tool. The engineer kind names a share, so
  a product's kind can spawn it, and a spawn of a kind that names none
  is refused. The spec and the lenses cite the engine at v0.5.0 and the
  guideline at v0.51.0 (#83).
- Reversed: an enabled `message_session` automation is refused when it
  is saved, and a stored one never acts, until the engine's budgets can
  end with a run; a disabled one saves. A standing session is woken by a
  person or by a product's own action meanwhile. ADR 2036 records it,
  and the spec and INT-07 say so (#85).
- `queue.work_items` is indexed by org, kind, target, and time, and
  `core.automation_runs` by status (#85).
- The engineer kind's step guard is sized for an engineering change
  (200), and its share follows from it (#85).
