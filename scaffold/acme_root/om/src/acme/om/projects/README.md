# Projects

What a tenant works on, and which work each session is part of. This is
one of the kinds of thing [Acme is made of](../../../../README.md).

## What it holds

- **Project**: a tenant's unit of work. It has a name and binds one
  repository. Several policies are set per project: what validates a
  change, where a workspace may reach, which secrets a command sees, and
  how long a session's content is kept.
- **Repository**: where a project's code lives, named by its host and
  its path, such as `github.com` and `octo/reports`. Names are compared
  without case, as the hosts compare them.
- **A session's project**: the project an [agent
  session](../agent_sessions/README.md) belongs to. It is set before the
  session exists, and it never changes.

## What can happen

- **Create a project.** The tenant's owners and admins create it, with
  its repository. The repository never moves.
- **Start a session under a project.** A session started here belongs
  to its project from its first moment. A project of another tenant is
  not found, and nothing is started. The API's start names the
  session's project, and outside `local` refuses a session that names
  none. An automation's start names none yet, so a session it starts
  takes its tenant's policies alone; naming one there is a change of its
  own.
- **Spawn or hand over.** A session that another session spawns, or
  hands work to, belongs to the same project as that session.
- **Ask a session's project.** A namespace that sets a policy per
  project asks here. A session with no project row answers none, never
  another project.
- **Ask where a session's work lands.** A session's own branch and pull
  request count as its work product only on its project's repository.
  Anywhere else, a write is an outward write.
- **Purge.** A session's project goes with the session when the session
  is purged. A deleted tenant's projects go when the tenant is purged.

## The rules

- **A session's project is its tenant's.** A session is never started
  under another tenant's project, and no tenant reads another's
  projects.
- **A session's project never moves.** It is set before the session
  exists: a second start under another project is refused, and so is a
  project named later for a session that already stands. The database holds this too: no serving login
  may rewrite or remove the row.
- **Work product lands on one repository.** A session's project's
  repository is the only one. A session with no project row has none,
  so no write of it is work product.

<!-- agents-only
`impl/sessions.py` holds the decorator over the engine's sessions
manager that the root wires in front of every other namespace: a session
created with a parent or a hand-over gets its origin's row first, and one
whose origin has none is refused when a row stands under its own id.
`impl/retention.py` answers retention's `SessionProjectInterface` from the
same row. `session_projects` is in `APPEND_ONLY_TABLES` and
`PURGED_TABLES`, so its row goes under the purge login. ADR 2016 records
the decisions.
-->

## How another namespace composes it

The root wires the projects' decorator in front of the [agent
sessions](../agent_sessions/README.md), and the projects start a root
session through the [agents](../agents/README.md). A namespace that keys
a policy by project reads `project_of`, and
[retention](../retention/README.md) takes a new session's project from
here; one that judges an outward write reads `work_repository`.
[Automations](../automations/README.md) start their sessions through the
projects' start, in the project an automation's action names.
