# Workspaces

The place a session's tools work, as the platform keeps it. This is one
of the kinds of thing [Acme is made of](../../../../README.md).

A **workspace** is a checkout: the session's branch, inside an instance
a host prepared. The branch, its commits, and the artifacts live
elsewhere, so a workspace is a cache, and the platform keeps what it is
rebuilt from.

## What it holds

- **A session's workspace**, one per session, under the session's id. It
  holds the isolation **pinned** when the session was created: the
  level, the limits, and the egress its project allowed then, with where
  that egress came from. It also holds what the cache knows between
  loops: the session's branch, whether the remote has held it, the last
  snapshot of its work, and what the next loop is told.
- **A project's fetch credential**, one per project: a read-only
  credential of the repository it binds. Its value is in the tenant's
  store; the record here says who gave it, and when.
- **A session's push token**, as its digest and its expiry on the
  session's workspace: the one token that writes the session's branch
  and its pull request.
- **A project's egress allowlist**, one per project: the destinations a
  workspace reaches and the methods each takes, or open egress, chosen
  on purpose and recorded with its reason and who chose it.
- **The levels**, as the engine names them: a VM per session, a
  container per session, a directory on a host, and the twin, which
  plays the lifecycle for tests in `local` alone.

## What can happen

- **Pin.** A session is pinned as it is created, before the engine
  writes it: its kind's level and limits at the version it starts on,
  and its project's allowlist as it stands. A kind that takes no egress
  keeps none, whatever its project allows. A session of no project keeps
  its kind's own egress. A later write of the allowlist reaches only the
  sessions created after it.
- **Prepare.** Before a loop's first model call, the workspace is
  prepared to the pin, whatever the loop asks. The host refuses what it
  cannot give before its provider is reached, and the provider refuses
  what it cannot meet: either way the loop parks on `resource` and asks
  again after a wait, and no weaker workspace is made ([ADR
  2005](../../../../../docs/adr/2005-a-workspace-no-host-can-give-parks-the-loop-and-a-lost-one-ends-it.md)).
  Then the checkout is brought up to the session's branch on the
  repository its project binds.
- **The branch.** One the remote holds is tracked, fast-forwarded to
  what the remote holds, and one never pushed is kept, or cut from the
  default branch on the session's first loop. One the remote held and
  lost is rebuilt from the default branch only when its pull request was
  merged or closed, and the loop is told. One that moved on both sides,
  or vanished for no known reason, ends the loop, loudly; nothing
  restarts silently from the default branch. Before any cut, what the
  checkout holds is pushed to a snapshot ref, or nothing is cut.
- **Release.** Before an instance goes, what its checkout holds that the
  remote lacks is committed to a snapshot ref beside the session's
  branch, never on it, and pushed. The branch, the index, and the files
  stay as they were. A push that does not land lets nothing go: the
  instance and its work stay. The next loop is told where the work is.
- **Egress.** The egress proxy asks for each connection. A metadata
  endpoint, the host itself, the platform's internal network, and a
  station's network are never reached, under any egress, by name or by
  the address a name resolves to. Then no egress refuses all, open
  egress allows the rest, and an allowlist allows a destination and port
  it names, by a method that rule takes.
- **Outward.** A push to the session's own branch or its snapshots, and
  its own pull request, on the one repository its project binds, are its
  work product. Every other write acts outward, for the rule of two.
- **Give a fetch credential.** A person who manages the tenant's members
  gives a project's repository one, and a later one replaces it.
- **Mint a push token, and write with it.** A token is minted for the
  session's branch on its project's repository. It writes that branch,
  its snapshots, and its pull request, and nothing else, through source
  control, which writes with the integration's own credential. It ends
  when its lifetime passes, when the loop's workspace is prepared again
  or released, or when a newer one is minted.
- **Purge.** A tenant deleted past its retention loses its workspaces,
  its allowlists, and its fetch credentials, each value out of the store
  before its record.

## The rules

- **Isolation is pinned, probed, and refused; never weakened.** A
  prepare is held to the pin, and the host that cannot give it refuses
  before the first model call.
- **The cloud never runs a session on a shared host.** A bare directory
  runs only on a host inside a customer's wall, as a dedicated,
  unprivileged user, with its egress enforced. A host that offers only a
  directory runs one session at a time, unless its owner says otherwise.
  Outside `local`, open egress needs a host that keeps it off the
  platform's insides, and an allowlist needs a proxy that holds its
  methods.
- **A workspace is a cache of durable state.** What a loop leaves is
  pushed before its instance goes, and a vanished branch is rebuilt only
  when its fate is known. An instance a dead run left is released the
  same way by its host's
  [runner sweep](../../../../../workers/session_runner/README.md), past a
  grace.
- **The agent never holds a repository's credential**
  ([ADR 2022](../../../../../docs/adr/2022-a-repositorys-credentials-are-the-platforms-and-the-agent-never-holds-one.md)).
  The fetch credential reaches only the platform's own read, and the
  push token only the platform's check; neither is in a workspace.
- **Egress is an allowlist of destinations and methods.** Open egress is
  a recorded choice, and what is never reached is never reached.

## How another namespace composes it

- The root decorates the engine's sessions manager, so every session is
  pinned as it is created, and the engine's tools manager, so every
  workspace is held to its pin. The loop sees the engine's interfaces.
- The checkout runs in the workspace through the engine's transport,
  under the epoch of the run that holds the session.
- A session's project and the repository it binds are the projects'
  rows, read through `WorkspaceProjectsInterface`; a repository is cloned
  over HTTPS and cut from its own default branch. A gone branch's fate
  comes from `PullRequestsInterface`, whose null knows none, so a branch
  gone for any reason ends the loop.
- What a host offers beyond its provider is a `HostOffer`, its owner's
  and its probe's. The default offers nothing more: a host of the
  platform's cloud.
- A tool that writes to source control sets its target's `outward` from
  `WorkspacesManagerInterface.outward`.
- The evidence reads what a session delivered (`impl/work_product.py`):
  its branch as the bound repository holds it, fetched into a fresh
  repository of the platform's own with nothing of the agent's config,
  refs, or replacements (`impl/reader.py`), giving the base, the head,
  and the paths changed; and dirty when the checkout this host holds has
  work that is not there. A private repository is read with its
  project's fetch credential, handed to that git alone.
- The engineer's pull request goes through
  `WorkspacesManagerInterface.open_pull_request`, which checks the push
  token and writes through `SourceControlInterface` (`projects.py`); the
  root wires the forge's (`impl/forge.py`), and with none every write is
  unavailable.
