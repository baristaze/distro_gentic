# Agent workspaces

The place a session's tools work, as the platform keeps it. This is one
of the kinds of thing [Acme is made of](../../../../README.md).

A **workspace** is a checkout: the session's branch, inside an instance
a host prepared. The branch, its commits, and the artifacts live
elsewhere, so a workspace is a cache, and the platform keeps what it is
rebuilt from.

## What it holds

- **A session's workspace**, one per session, under the session's id. It
  holds the isolation **pinned** when the session was created: the
  level, the limits, and the egress its agent project allowed then, with
  where that egress came from, and its **durability** and base: its
  kind's, a cache where its agent project keeps its sessions' workspaces
  as caches, and, for a kind that takes it, the base its agent project's
  workspace base names. It
  also holds what the cache knows between
  loops: the session's branch, whether the remote has held it, the last
  snapshot of its work, and what the next loop is told.
- **An agent project's fetch credential**, one per agent project: a
  read-only credential of the repository it binds. Its value is in the
  tenant's store; the record here says who gave it, and when.
- **A session's push token**, as its digest and its expiry on the
  session's workspace: the one token that writes the session's branch
  and its pull request.
- **An agent project's egress allowlist**, one per agent project: the
  destinations a workspace reaches and the methods each takes, or open
  egress, chosen on purpose and recorded with its reason and who chose
  it.
- **Where each snapshot of a session lives**, one record per snapshot
  it keeps, a fork's copy included: the platform's bucket, or the store
  of a host of the session's pool, by its reference, the digest the host
  declared, its size, and the hash its step names. Never its bytes
  ([ADR 2050](../../../../../docs/adr/2050-a-snapshot-lives-on-its-workspaces-side-of-the-wall.md)).
- **A validation's instance**: one for each run of a delivery's checks,
  under an id nobody used, made by the platform's executor, or by a host
  of the pool a session inside its tenant's wall is pinned to, and
  destroyed when the run ends ([ADR 2024](../../../../../docs/adr/2024-a-validation-session-is-platform-work-on-the-fresh-executor.md)).
- **The levels**, as the engine names them: a VM per session, a
  container per session, a directory on a host, and the twin, which
  plays the lifecycle for tests in `local` alone.

## What can happen

- **Pin.** A session is pinned as it is created, before the engine
  writes it: its kind's level and limits at the version it starts on,
  and its agent project's allowlist as it stands. A kind that takes no
  egress keeps none, whatever its agent project allows. A session of no
  agent project keeps its kind's own egress. A later write of the
  allowlist reaches only the sessions created after it. A kind that
  takes its agent project's workspace base pins the base the workspace
  base names then, and keeps it: a changed workspace base reaches only
  the sessions created after it, and the first of them builds it where
  its workspace runs ([ADR
  2051](../../../../../docs/adr/2051-an-agent-projects-workspace-base-is-built-once-where-its-workspaces-run.md)).
- **Prepare.** Before a loop's first model call, the workspace is
  prepared to the pin, whatever the loop asks. The host refuses what it
  cannot give before its provider is reached, and the provider refuses
  what it cannot meet: either way the loop parks on `resource` and asks
  again after a wait, and no weaker workspace is made ([ADR
  2005](../../../../../docs/adr/2005-a-workspace-no-host-can-give-parks-the-loop-and-a-lost-one-waits-for-a-person.md)).
  Then the checkout is brought up to the session's branch on the
  repository its agent project binds, from a bundle the platform reads
  on its own host with the agent project's fetch credential; the
  checkout fetches nothing itself ([ADR
  2023](../../../../../docs/adr/2023-a-workspaces-repository-comes-in-and-its-work-goes-out-as-bundles-the-platform-makes.md)).
- **The branch.** One the remote holds is tracked, fast-forwarded to
  what the remote holds, and one never pushed is kept. Where nothing
  holds it, it is cut from its last snapshot, or from the default branch
  on the session's first loop. One the remote held and
  lost is rebuilt from the default branch only when its pull request was
  merged or closed, and the loop is told; a later cut starts there too,
  never from a snapshot of the old work. One that moved on both sides,
  or vanished for no known reason, parks the loop, loudly, for a person
  to say what comes next; nothing restarts silently from the default
  branch. Before any cut, what the
  checkout holds is pushed to a snapshot ref, or nothing is cut.
- **Release.** Before an instance goes, what its checkout holds that the
  remote lacks is committed to a snapshot ref beside the session's
  branch, never on it, and pushed: the platform bundles it, and source
  control pushes it with its own credential. The branch, the index, and
  the files stay as they were. A push that does not land lets nothing
  go: the instance and its work stay. The next loop is told where the work is. A
  release lets go only of what its own run holds, by the run's epoch: a
  session that resumes while it is still being released keeps the
  workspace its new run took.
- **Egress.** The egress proxy asks for each connection. A metadata
  endpoint, the host itself, and the platform's internal network are
  never reached, under any egress, by name or by the address a name
  resolves to. Then no egress refuses all, open
  egress allows the rest, and an allowlist allows a destination and port
  it names, by a method that rule takes.
- **Outward.** A push to the session's own branch or its snapshots, and
  its own pull request, on the one repository its agent project binds,
  are its work product. Every other write acts outward, for the rule of
  two.
- **Give a fetch credential.** A person who manages the tenant's members
  gives an agent project's repository one, and a later one replaces it.
  It is never read back. When its agent project is removed, its value
  leaves the tenant's store before its record goes.
- **Mint a push token, and write with it.** A token is minted for the
  session's branch on its agent project's repository. It writes that
  branch, its snapshots, and its pull request, and nothing else, through
  source control, which writes with the integration's own credential,
  through the installation of the forge that holds the repository, and
  only when the session's own tenant connected it. It ends
  when its lifetime passes, when the loop's workspace is prepared again
  or released, or when a newer one is minted.
- **Run a delivery's checks.** The platform's executor
  (`impl/executor.py`) makes a container with no egress for the run, on
  the workspace base the session pinned when it names one, such as its
  agent project's workspace base, so the checks find what its setup
  installed ([ADR
  2062](../../../../../docs/adr/2062-a-validations-checks-run-on-the-base-its-session-pinned-with-no-egress.md)).
  It writes in the tree the platform read from the agent project's
  repository: the delivered commit, with every protected path from the
  base, and no credential and no history. It runs each check's template
  there, reads back and hashes the results within their bound, and
  destroys the instance whatever ended the run. A trial that reaches no
  verdict (it ran past its time, or wrote no run of its check) is an
  `errored` run the executor writes, so every trial counts. For a
  session inside its tenant's wall, a host of its pool makes the
  instance instead, to the isolation the session is pinned to, with no
  egress when it is on a workspace base, and every step crosses the wall
  as `exec` work; no host of another pool or tenant takes it.
- **Keep a snapshot.** A workspace kept by snapshots is snapshotted at
  the end of each run that holds it: by the engine, into the platform's
  bucket, when this process holds it; by the host that holds it, into
  that host's own store, when a host of the session's pool does. A
  session that keeps no content at rest is refused such a kind when it
  is created, and a pool with no host that probed snapshots at its level
  keeps it waiting, never a cache in its stead.
- **Restore.** The next loop starts from the latest snapshot, decided
  before any host is asked: from the bucket here, or from a host's store
  through the prepare it travels with. A snapshot kept on one side of
  the wall never restores on the other. A restored tree stands: nothing
  of the branch is brought over it. A person who takes control gets it
  too, before the workspace is handed over.
- **Fork.** A spawn that forks a workspace a host holds asks that host
  to snapshot it as it stands, and to keep the copy in its own store as
  the child's. The child's first prepare restores it on a host of the
  pool, and the parent keeps nothing of it. A refusal comes before the
  tree's slot is taken or the child is made
  ([ADR 2061](../../../../../docs/adr/2061-a-fork-of-a-hosted-workspace-is-taken-by-its-host-and-kept-as-the-childs.md)).
- **Erase.** A revoked key takes the session's snapshots out of the
  bucket, asks each host that keeps one to erase it, and forgets their
  records.
- **Purge.** A session the sweep purges loses its workspace row with its
  files, and its snapshots: each host that keeps one is asked to erase
  it before their records go. A tenant deleted past its retention loses its workspaces, its
  allowlists, and its fetch credentials, each value out of the store
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
- **A snapshot lives on its workspace's side of the wall.** Its bytes
  stay in the store of the side that took it; the platform records the
  reference and the hash.
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

- The root names the kinds whose pin takes their agent project's
  workspace base, each by name and version: the platform's
  (`WORKSPACE_BASE_KINDS`), and those a product's slot names
  (`ProductKinds.workspace_bases`).
- The root decorates the engine's sessions manager, so every session is
  pinned as it is created, and the engine's tools manager, so every
  workspace is held to its pin. The loop sees the engine's interfaces.
- The checkout runs in the workspace through the transport the tools
  take, each command under the epoch its run held when it began, so a run
  that lost its claim moves nothing: for a session
  pinned to its tenant's hosts, the exec relay to the host that holds
  it. Nothing it runs reaches the repository: a bundle comes in through
  the transport's files, and one goes out the same way.
- A pinned session's workspace is made by a host of its pool, not by this
  process (`placed.PlacedWorkspacesInterface`, the exec relay's): it is
  held to the same pin, and its loop waits on the resource until a host
  holds it.
- A session's agent project and the repository it binds are the agent
  projects' rows, read through `WorkspaceAgentProjectsInterface`; a
  repository is read over HTTPS on the platform's host
  (`impl/reader.py`), with the tags in its branches' history, and a
  branch cut from its own default branch. The read reaches only where a
  workspace may: a host any of whose addresses is in a network no
  workspace reaches is refused before anything is fetched, git is held
  to the addresses checked, and no redirect is followed. The root walls
  off what the options name; in `local`, a repository on disk is read
  too. A gone branch's fate comes from `PullRequestsInterface`, whose
  null knows none, so a branch gone for any reason parks the loop for a
  person.
- Outside `local`, the evidence's executor is this namespace's: the root
  builds it over infra's provider and transport for a session of the
  cloud, and over the exec relay's instances
  (`PlacedInstancesInterface`, in `placed.py`) for one inside its
  tenant's wall, and reads its tree through `checks_tree`.
- What a host offers beyond its provider is a `HostOffer`, its owner's
  and its probe's. The default offers nothing more: a host of the
  platform's cloud.
- A tool that writes to source control sets its target's `outward` from
  `AgentWorkspacesManagerInterface.outward`.
- The evidence reads what a session delivered (`impl/work_product.py`):
  its branch as the bound repository holds it, fetched into a fresh
  repository of the platform's own with nothing of the agent's config,
  refs, or replacements (`impl/reader.py`), giving the base, the head,
  and the paths changed; and dirty when the checkout this host holds has
  work that is not there. A private repository is read with its agent
  project's fetch credential, handed to that git alone.
- The software engineer's pull request goes through
  `AgentWorkspacesManagerInterface.open_pull_request`, which checks the push
  token, refuses a body with an image or a URL off the repository's host,
  since the forge renders it, bundles the committed head out of the
  workspace this host holds, and writes through `SourceControlInterface`
  (`agent_projects.py`): the one head, to the session's branch alone,
  forward only. The root wires the forge's (`impl/forge.py`), and with
  none every write is unavailable.
