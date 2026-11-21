# ADR 2072: A person's own client serves their session's local workspace, and follows any other

**Status**: accepted (2026-11-20)

## Context

A session's workspace runs in the cloud pool, on a VM of its own
([ADR 2052](2052-the-cloud-pool-runs-a-vm-per-session-whose-host-pulls-its-work.md)),
or on a host of a tenant's pool, which its owner installs as a service,
enrolls with an enrollment token, and pins the session to
([ADR 2003](2003-a-host-enrolls-once-and-holds-its-owners-ceilings-on-its-own-disk.md)).
A person who wants the agent to work on their own machine, from their
own terminal, has only the second path, which is an owner's: an
enrollment token needs the members permission, and a pool serves every
session pinned to it.

The pieces of a lighter path exist. The host program's claim loop holds
the exec relay and the owner's ceilings. The cloud pool gives each
session a pool of one, and its VM's host trades a one-use key for a
credential of that pool, which claims that session's work alone.

## Decision

**A session's workspace is the cloud's or local.** A session starts
with `workspace` `cloud`, the default, or `local`. A kind that asks for no workspace has none, and is
refused `local`. A local session is pinned, as it starts, to a pool of
one of its own (`local_pool_id`), apart from its pool in the cloud pool,
so a principal who moves it to the cloud never shares a pool between a
VM and a person's machine. The tenant does not list that pool, issue a
token for it, or place another session on it.

**Its person's client serves it on a key of that session.** The person
who started the session asks for a client key
(`POST /v1/agent-sessions/{id}/workspace-keys`): one-use, of its own
prefix (`hck_`), five minutes long, kept as a digest beside the
enrollment tokens. Their CLI runs the host program's own claim loop,
which trades the key at the host's enrollment
(`POST /v1/hosts/enrollments`) for a host's credential of the session's
pool, carrying the session in its identity. The host serves the
session's tree: placement hands it the work of the session, of its
sub-agents, which run where their root runs, and of the instances their
checks ask for, each read up to the root of the session it names, and
fails any other session's item that reaches it. The trade spends the
key, and refuses it when the session left its pool, or the person left
the tenant or no longer writes its sessions. The person answers for the host. Its
credential lives in a temporary home only its user reads, which goes as
the client stops; the owner's ceilings, secrets, and snapshots are the
host's own home's.

**One client at a time, and a client gone is a host gone.** A new
client's trade ends every host that served the session before. A client
ends its own host as it stops (`DELETE /v1/hosts/me/credentials`). With
no client, the session's next workspace call waits on the resource, as a
pinned session with no host online does
([ADR 2005](2005-a-workspace-no-host-can-give-parks-the-loop-and-a-lost-one-waits-for-a-person.md)),
and never moves to the cloud. A client that serves again prepares the
workspace anew from the session's branch, since a workspace is a cache.

**Any other session is followed.** A key for a session whose workspace a
VM of the cloud pool, a host of a pool, or another person's client
holds is refused as `workspace_held_elsewhere`. The CLI reads it as
"follow": it streams the session's steps and serves nothing.

**The container is a local workspace's wall, and a refusal names its
ceiling.** A local workspace is a container on the person's own engine,
as the host program makes one, and the container is its wall. The
owner's ceilings stay as every host holds them, and each refusal names
the ceiling that refused, so a person who wrote the file reads which
line stopped an item. No ceiling lists the programs a command may start.
The platform's own scripts run through a shell (`sh -c`): the checkout's
sync, which runs around every loop of a session bound to a repository,
and an instance's unpack, copy, and lock steps. A list without the shell
refuses every local session that works on a repository, and a list with
it lets any command through. A list of programs is no wall for a command
that runs through a shell. Such a list waits for a transport that runs
a bare directory as a dedicated user, where no container stands between
a command and the machine.

## Consequences

- A person serves their own session from their laptop with the CLI's
  `serve` extra and a `ceilings.toml` of their own, and no enrollment
  token. A machine whose owner wrote no ceilings serves nothing.
- A local workspace is one the host program gives: a container per
  session. A directory on the person's own checkout waits for a
  transport that runs a bare directory as a dedicated user
  ([ADR 1021](1021-a-host-directory-runs-its-commands-as-an-account-of-its-own-one-workspace-at-a-time.md)).
- A client restarted prepares the workspace again, on a new host. A
  client killed without its stop keeps its host until it falls silent,
  and the session waits for that host meanwhile.
