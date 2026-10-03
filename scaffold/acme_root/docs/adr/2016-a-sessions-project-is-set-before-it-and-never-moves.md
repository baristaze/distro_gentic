# ADR 2016: A session's project is set before it, and never moves

**Status**: accepted (2026-10-02)

## Context

The platform's spec keys several policies by project: a validation
policy, an egress allowlist, an environment secret, a limit's scope, the
projects a host serves, and retention's narrowing. Under Trust,
Exfiltration, a session's own branch and its pull request on the bound
repository are its work product, never an outward write. The engine has
no project: its session names a tenant, a kind, and where it came from.
Without one, each per-project policy falls back to its tenant's, and a
project's narrowing never applies.

## Decision

**A project is its tenant's and binds one repository.** One who writes
the tenant's configuration (`manage_members`) writes it, renames it, and
removes it while no session belongs to it. Its repository never moves, so the work product of a session already in
it stays where it was. A repository is a host and a path, kept in lower
case, since the hosts compare names without case.

**A session's project is a row of its own, written before the session.**
The engine's session is left as it is. The projects' start writes the
row, keyed by the session's id, then starts the session through the
agents. So a namespace asked while the session is created already finds
the project. The start refuses a project another tenant holds, before
anything is written.

**Nothing moves a session to another project.** A start under another
project is `ProjectFixed`. So is a start for a session that stands
already, since it was created under none. The database holds it as well:
the table is append-only for the serving logins, as the history is
([ADR 1002](1002-the-history-is-written-once-and-a-stale-run-is-refused.md)),
and the purge login removes a row with its session or its tenant
([ADR 1010](1010-a-history-is-purged-by-a-login-of-its-own.md)).

**A spawned or handed-over session belongs where it came from.** A
decorator over the engine's sessions manager, wired in front of every
other namespace, writes the origin's row for the new session before the
engine writes it. A session whose origin has no project gets none: a
row already standing under its id is `ProjectFixed`. So a child never
escapes into its tenant's looser policies, and never into a project its
origin is not in.

**A session started through the projects belongs to its project.** The
engine's own start stays beneath the projects' start. The API's start
names the session's project and starts it through the projects, and
outside `local` it refuses a session that names none. A session started
in no project, as a local stack may, has no row and takes its tenant's
policies alone: `project_of` answers None, never another
project, and `work_repository` none, so no write of it is work product.

**An automation's session starts through the projects' start,** in the
project its action names, which is read as the tenant's when the
automation is saved. Outside a local stack, an automation whose start
names none is refused when it is saved, and one stored with none starts
nothing when it fires
([ADR 2017](2017-a-schedule-fires-once-a-slot-and-an-automations-principal-is-a-grant.md)).

## Consequences

- Each namespace that keys a policy by project reads it through
  `ProjectsManagerInterface`, and its own stand-in for a session's
  project is wired to it.
- A session an automation starts is held by its project's budget and
  policies from its first moment.
- A start that fails after its row is written leaves the row. A retry
  under the same id and project goes on from it; any other use of the
  id is refused.
- The API's start and an automation's each name a project, and outside
  `local` each refuses a session without one.
