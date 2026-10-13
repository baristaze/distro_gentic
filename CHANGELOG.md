# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.18.0 (2026-10-12)

Every state a person can reach has a known way out. The platform's base
moves to the engine at v0.17.0: a park names its cause and a route that
clears it, one person steers a session, a session is the org's or
private, and a hand-over is its holder's. The platform's own parks on
money have routes, and a saved key or a fixed price wakes the sessions
that waited on it. The portal shows End this run beside Give it back,
and Sessions lists a person's own first and the org's to join. Minor,
with three reversals named: a mapped member who does not steer comments
as data, control of another person's hand-over answers `409`, and Run
and Give it back show to a hand-over's holder alone.

### Added

- From the engine's v0.17.0, in the scaffold: parks with a cause and a
  route, one steerer for each session, org-wide or private visibility,
  and a hand-over that names its holder. Session decorators, trust, and
  watch take them; the session list keeps its cursor, newest first, and
  takes `among`; the watch's give-back body is `ControlGiveBackRequest`
  (#158).
- Billing parks with a way out: each park on the tenant's money has a
  route, held to billing's permission, that wakes its sessions and
  answers the ledger entry it posted: a call's cost approval, a budget's
  raise for its window, a confirmed payment, and an operator's grant. A
  saved key wakes the sessions parked on a missing or refused key and
  tells those who save keys what waits; an own-key account or permission
  park tells the org's admins once; a price park retries every five
  minutes and names the operator (ADR 2060) (#161).
- Sessions: two views, Yours first (`among=mine`: made or joined) and
  The org's with Join, org-wide only and never a private one, even for a
  role that audits. A session's header says who steers and who sees it;
  its panel joins, switches visibility, adds members, hands the steer
  on, or takes a lapsed one. A participant who does not steer writes a
  suggestion (#160).
- The portal shows End this run on a hand-over, beside Give it back and
  in the header's menu. The spec says what a second start does for a
  session, a validation session, and an automation's run, and that every
  resume the platform offers has the cancel beside it (#159).

### Changed

- Intake: a mapped user instructs only a session they steer; a push
  parks a session on a hand-over naming no holder, since `take_over` is
  in person (#158).
- Lists hold root sessions the caller sees, and sub-agents come through
  the children route; the left bar holds the person's own sessions, and
  the toast goes to the steerer (#158, #160). `/v1/approvals` and
  `list_sessions` include each visible root's sub-agents (#161).
- A park by a missing or refused key is told by its cause, never as a
  rate limit (#161).
- The platform's core migrations take stamps above the engine base's
  head (#158).

### Removed

- A mapped member who does not steer no longer instructs a session:
  their message is data. A reversal (#158).
- Control of another person's hand-over answers `409`. A reversal
  (#158).
- Run and Give it back show to a hand-over's holder alone; another
  member sees who holds it and End this run. A reversal (#159).
