# Agent projects

What a tenant works on, and which work each session is part of. This is
one of the kinds of thing [Acme is made of](../../../../README.md).

## What it holds

- **Agent project**: a tenant's unit of work. It has a name and binds
  one repository. Several policies are set per agent project: what
  validates a change, where a workspace may reach, which secrets a
  command sees, how long a session's content is kept, and the workspace
  base its sessions' workspaces start from.
- **Workspace base**: what an agent project's sessions work in, if it
  names one: an image, the commands that set it up, and the package
  registries the setup reaches. It is built once and kept, and a session
  of a kind that takes it starts from it with no network of its own
  ([workspaces](../agent_workspaces/README.md)).
- **Repository**: where an agent project's code lives, named by its host
  and its path, such as `github.com` and `octo/reports`. Names are
  compared without case, as the hosts compare them.
- **A session's agent project**: the agent project an [agent
  session](../agent_sessions/README.md) belongs to. It is set before the
  session exists, and it never changes.

## What can happen

- **Create an agent project.** The tenant's owners and admins create it,
  with its repository. The repository never moves.
- **Set an agent project's workspace base.** The owners and the admins
  set it, replace it, or take it away. It reaches the sessions created
  after it; a session keeps the one it started on.
- **Rename or remove an agent project.** The owners and the admins
  rename it, and remove it while no session belongs to it. An agent
  project with sessions stays: they read their policies and their work
  product through it. Its repository's fetch credential goes with it
  ([workspaces](../agent_workspaces/README.md)).
- **Start a session under an agent project.** A session started here
  belongs to its agent project from its first moment. An agent project
  of another tenant is not found, and nothing is started. The API's
  start names the session's agent project, and outside `local` refuses a
  session that names none. An agent automation's start names its agent
  project too, and outside `local` one that names none starts nothing.
- **Spawn or hand over.** A session that another session spawns, or
  hands work to, belongs to the same agent project as that session.
- **Ask a session's agent project.** A namespace that sets a policy per
  agent project asks here. A session with no agent project row answers
  none, never another agent project.
- **Ask where a session's work lands.** A session's own branch and pull
  request count as its work product only on its agent project's
  repository. Anywhere else, a write is an outward write.
- **Purge.** A session's agent project goes with the session when the
  session is purged. A deleted tenant's agent projects go when the
  tenant is purged.

## The rules

- **A session's agent project is its tenant's.** A session is never
  started under another tenant's agent project, and no tenant reads
  another's agent projects.
- **A session's agent project never moves.** It is set before the
  session exists: a second start under another agent project is refused,
  and so is an agent project named later for a session that already
  stands. The database holds this too: no serving login may rewrite or
  remove the row.
- **Work product lands on one repository.** A session's agent project's
  repository is the only one. A session with no agent project row has
  none, so no write of it is work product.

<!-- agents-only
`impl/sessions.py` holds the decorator over the engine's sessions
manager that the root wires in front of every other namespace: a session
created with a parent or a hand-over gets its origin's row first, and one
whose origin has none is refused when a row stands under its own id.
`impl/retention.py` answers retention's `SessionAgentProjectInterface`
from the same row. `agent_session_projects` is in `APPEND_ONLY_TABLES`
and `PURGED_TABLES`, so its row goes under the purge login. ADR 2016
records the decisions.
-->

## How another namespace composes it

The root wires the agent projects' decorator in front of the [agent
sessions](../agent_sessions/README.md), and the agent projects start a
root session through the [agents](../agents/README.md). A namespace that
keys a policy by agent project reads `agent_project_of`, and
[retention](../retention/README.md) takes a new session's agent project
from here; one that judges an outward write reads `work_repository`.
[Agent automations](../agent_automations/README.md) start their sessions
through the agent projects' start, in the agent project an agent
automation's action names.
