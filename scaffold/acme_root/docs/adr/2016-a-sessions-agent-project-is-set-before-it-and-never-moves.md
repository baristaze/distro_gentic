# ADR 2016: A session's agent project is set before it, and never moves

**Status**: accepted (2026-10-02)

## Context

The platform's spec keys several policies by agent project: a validation
policy, an egress allowlist, an environment secret, a limit's scope, the
agent projects a host serves, and retention's narrowing. Under Trust,
Exfiltration, a session's own branch and its pull request on the bound
repository are its work product, never an outward write. The engine has
no agent project: its session names a tenant, a kind, and where it came
from. Without one, each per-agent-project policy falls back to its
tenant's, and an agent project's narrowing never applies.

## Decision

**An agent project is its tenant's and binds one repository.** One who
writes the tenant's configuration (`manage_members`) writes it, renames
it, and removes it while no session belongs to it. Its repository never
moves, so the work product of a session already in it stays where it
was. A repository is a host and a path, kept in lower case, since the
hosts compare names without case.

**A session's agent project is a row of its own, written before the
session.** The engine's session is left as it is. The agent projects'
start writes the row, keyed by the session's id, then starts the session
through the agents, so a namespace asked while the session is created
already finds the agent project. The start refuses an agent project
another tenant holds, before anything is written.

**Nothing moves a session to another agent project.** A start under
another agent project is `AgentProjectFixed`. So is a start for a
session that stands already, since it was created under none. The
database holds it as well: the table is append-only for the serving
logins, as the history is ([ADR
1002](1002-the-history-is-written-once-and-a-stale-run-is-refused.md)),
and the purge login removes a row with its session or its tenant ([ADR
1010](1010-a-history-is-purged-by-a-login-of-its-own.md)).

**A spawned or handed-over session belongs where it came from.** A
decorator over the engine's sessions manager, wired in front of every
other namespace, writes the origin's row for the new session before the
engine writes it. A session whose origin has no agent project gets none:
a row already standing under its id is `AgentProjectFixed`. So a child
never escapes into its tenant's looser policies, and never into an agent
project its origin is not in.

**A session started through the agent projects belongs to its agent
project.** The engine's own start stays beneath the agent projects'
start. The API's start names the session's agent project and starts it
through the agent projects, and outside `local` it refuses a session
that names none. A session started in no agent project, as a local stack
may, has no row and takes its tenant's policies alone:
`agent_project_of` answers None, never another agent project, and
`work_repository` none, so no write of it is work product.

**An agent automation's session starts through the agent projects'
start,** in the agent project its action names, which is read as the
tenant's when the agent automation is saved. Outside a local stack, an
agent automation whose start names none is refused when it is saved, and
one stored with none starts nothing when it fires
([ADR
2017](2017-a-schedule-fires-once-a-slot-and-an-agent-automations-principal-is-a-grant.md)).

## Consequences

- Each namespace that keys a policy by agent project reads it through
  `AgentProjectsManagerInterface`, and its own stand-in for a session's
  agent project is wired to it.
- A session an agent automation starts is held by its agent project's
  budget and policies from its first moment.
- A start that fails after its row is written leaves the row. A retry
  under the same id and agent project goes on from it; any other use of
  the id is refused.
