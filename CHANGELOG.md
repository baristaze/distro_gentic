# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.17.0 (2026-10-12)

The platform defines, runs, and hosts agents, and its agent kinds are
its heart. Its base moves to the engine at v0.16.0: toolsets, a model
size and an effort per role, standing text, and an MCP client. The
platform's kinds are built from toolsets, ask a model size the matrix
answers, and keep their workspace warm for their own grace. A playbook
is invoked into a session, or pinned to a kind as its manual. A tenant
connects its MCP servers as toolsets of its kinds, and one inside the
wall runs on its host. A reviewer and an operator ship as templates.
The levers a tenant customizes an agent with are read before they ship,
and read back from the sessions that stalled. Minor, with two reversals
named: the runner's grace setting is gone, and a matrix version is
published only with a row for each size a shipped kind asks.

### Added

- The lever review: pure checks read each published playbook and
  reviewed knowledge entry for a repeated phrase, a must and a must-not
  on one subject, a name no kind holds, a retry with no stop, and a size
  past what a session holds whole; a finding advises and stays with its
  version, and a version never read answers null, shown as not checked.
  An operator reads which levers came before stalls
  (`GET /v1/admin/orgs/{org_id}/levers`, `acme-ops levers`), and the
  skill `audit-agent-levers` ranks them (ADR 2054) (#150).
- From the engine's v0.16.0, in the scaffold: toolsets and
  `load_toolset`, a kind's asks, standing text in the cached system
  layer, and the MCP client. The matrix resolver takes a kind's asks
  (#151).
- Toolsets: the platform's tools form eight (files, code, knowledge,
  delivery, sub_agents, records, handoff, artifacts), every shipped kind
  version is rebuilt from them with the same bytes, and a product's slot
  adds its own. Shipped kinds ask L of main and S of the summarizer. The
  matrix keys on a size: of a version holding a row for the asked size,
  a row naming the kind answers first, then size rows, then the rest; of
  any other version every question answers as before. A kind carries
  its warm grace, at most the prompt cache's life (ADR 2055) (#152).
- Playbooks invoked and pinned: a person invokes one into a session
  (`POST /v1/playbooks/{name}/invocations`, `acme playbook invoke`, the
  session page), and an automation's start may name one. A person who
  manages the tenant pins a playbook's version to a kind as its manual
  (`/v1/playbook-pins`), and each later session of the kind holds it as
  standing text, its gates only narrowing (ADR 2056) (#153).
- A reviewer and an operator, built from toolsets: the reviewer reads a
  pull request through the forge and submits findings with file and
  line through a gate that checks its own reads; the operator reads
  sessions, waits, hosts, and spend. A kind that may only read is held
  to its reach at boot (ADR 2058) (#154).
- Connectors: a tenant connects an MCP server, reviews its tools at
  pinned hashes, and attaches it to a kind as a deferred toolset; a
  server inside the wall is named in its host's ceilings and called as
  `exec` work, so the platform opens no connection into the wall
  (ADR 2057) (#155).

### Changed

- The README and the spec open on defining, running, and hosting agents,
  with the kinds as templates a product copies (#156).
- The forge's integration reads a pull request and a file back (#154).
- `build_managers` takes an agents layer every session's start, spawn,
  and hand-off passes through (#153); the loop takes an
  `AttachedToolsetsInterface`, a null object by default (#155).

### Removed

- `ACME_RUNNER_WORKSPACE_GRACE_SECONDS`: a kind's own grace replaces it.
  A reversal (#152).
- A matrix version without a row for each size a shipped kind asks (L,
  S, and the reviewer's XL) is no longer published. A reversal (#152,
  #154).
