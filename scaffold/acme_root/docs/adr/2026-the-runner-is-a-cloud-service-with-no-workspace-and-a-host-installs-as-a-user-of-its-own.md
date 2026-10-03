# ADR 2026: The runner is a cloud service with no workspace, and a host installs as a user of its own

**Status**: accepted (2026-10-03)

## Context

[ADR 1011](1011-a-sessions-loop-runs-in-a-worker-of-its-own.md) gives a
session's loop a worker of its own, and leaves it out of the cloud: a
deployed runner refuses a workspace on its host, and a Fargate task
starts no container. The first environment that runs a loop deploys it,
"with its image, its service, its alarms, and a place its workspaces
run". Until then a session deployed to staging or production waits for a
runner that never comes.

The place a tenant's work runs already exists: a host inside the
tenant's wall, enrolled once
([ADR 2003](2003-a-host-enrolls-once-and-holds-its-owners-ceilings-on-its-own-disk.md)),
to which every tool call crosses as keyed `exec` work
([ADR 2004](2004-a-tool-call-crosses-the-wall-as-keyed-exec-work-and-runs-once.md)).
What it lacks is a way in: a tenant installs it by hand, under whatever
user that person picks, root included.

## Decision

**The runner is a service in each environment, and it prepares no
workspace.** It ships as an image of its own, built once by the commit
on `main`, planned and recorded with the API's, and carried to
production by its digest on `release`. It rolls after the API's
migration, one task at a time, with a count and a ceiling set in the
environment's root. It runs with `ACME_WORKSPACE_BACKEND=none`: a
session's tools run on a host of its tenant's pool, through the relay,
and a session that asks the runner itself for a workspace is refused
before its first model call.

**Its role reads what a loop reads, and writes no secret.** Its task role
holds the buckets, the key, and a read of a tenant's own secrets under
the application prefix. It reaches no inbound queue, since its work is a
work item on its loop lane, and never the grant that writes and deletes
a tenant's secrets. Its execution role injects the serving logins, the
error tracker's DSN, and the platform's model keys. Each key holds "off"
until a person writes one, so a new environment spends nothing on the
platform's account.

**A host installs as a service of a user of its own.** On Linux,
`deployment/host/install.sh` makes a system user for it, builds its
release from the lock into a prefix root owns, and writes its settings
where only root reads them. Its unit starts it as that user with no
capability and no way to gain one, the machine read-only around its own
state, its owner's ceilings bound read-only into its home, and a rootful
container engine's socket out of reach. Its engine is a rootless one, run
as the same user. On macOS it is a launchd agent of the person who
installs it, and the installer refuses root.

## Consequences

- An unpinned session in the cloud has no workspace. When one needs
  tools there, the cloud gets a workspace pool of its own: instances
  with a container engine, outside Fargate.
- The runner's connections count in the pool rule beside the API's and
  the worker's, and its ceiling is a line of its own
  ([deployment/cloud/README.md](../../deployment/cloud/README.md)).
- A host cannot rewrite its code, its ceilings, or its settings, so a
  command that escapes into the host's process keeps what that process
  holds and no more: its credential and its secret store.
- On macOS the ceilings are their owner's word, not a wall: the host
  runs as the person who owns the file.
- `make host-check` installs the host in a container with systemd and
  holds its user, its capabilities, what it can write, and its unit's
  exposure; CI runs it.
