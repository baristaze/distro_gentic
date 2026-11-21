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
pool, carrying the session in its identity, so placement fails any other
session's item that reaches it. The trade spends the key, and refuses it
when the session left its pool, or the person left the tenant or no
longer writes its sessions. The person answers for the host. Its
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

**The owner's ceilings name the programs a command starts.** The host's
`ceilings.toml` gains `commands`: the programs a command may start, by
name or absolute path, none unless named, or `all`. The relay reads what
a command runs once it holds the item's detail, and refuses a program
the list does not name, and a command that sets the search path a named
program is found on, before anything starts. Every ceiling's refusal
names the ceiling. A VM of the cloud pool names `all`: the VM is its
session's wall.

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
- `commands` is a net on the program a command names. A command that
  runs a named interpreter runs what that interpreter runs, and a base's
  setup runs as a prepare does, outside it.
- An installed host's `ceilings.toml` without `commands` runs no
  command: its owner names the programs, or `all`.
