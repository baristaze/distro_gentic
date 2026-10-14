# ADR 2050: A snapshot lives on its workspace's side of the wall

**Status**: accepted (2026-10-11)

## Context

The engine snapshots a workspace whose spec asks for it: the run that
holds it takes the snapshot at its end, the next run starts from the
latest one, a principal rewinds to an earlier one, and a fork copies one
at the spawn ([ADR 1027](1027-a-workspace-is-snapshotted-whole-and-a-restore-a-rewind-or-a-fork-starts-from-it.md),
[ADR 1030](1030-a-fork-starts-from-its-parents-workspace-as-it-stands-at-the-spawn.md)).
It leaves the rest to a platform: which workspaces are kept by
snapshots, where a snapshot lives relative to a customer's wall, and how
long it is kept.

The platform held every prepare to the session's pin, which kept the
isolation alone. A kind that asked for snapshots or a base was refused,
so no session of the platform's could resume on its whole machine. A
workspace on a customer's host is made and run by that host, through the
exec relay, and the host holds no key of the platform's, so the engine's
snapshot, taken by the process that runs the loop and sealed into the
platform's bucket, cannot reach it.

## Decision

**A kind chooses, and an agent project narrows.** A kind's isolation
says its durability, `cache` or `snapshot`, and its base. The pin keeps
both with the isolation, so every prepare of the session is held to
them. An agent project that keeps its sessions' workspaces as caches
(`workspace_snapshots` false) pins each of them a cache. A session that
keeps no content at rest is refused a kind kept by snapshots when it is
created: each snapshot of it would be refused, and its instance kept
live for good.

**A snapshot lives where its workspace lives.** A workspace this
process prepares is snapshotted by the engine, sealed into the
platform's bucket. A workspace a host holds is snapshotted by that host,
through the exec relay: a `snapshot` work item on its lane. The host
takes back what its broker attached, takes the snapshot of the instance
its provider holds by its labels, scans it for the value of every secret
it keeps for the tenant, and keeps it in its own store, owner-only. It
answers the reference, the SHA-256 of the bytes, and their size. The
platform records where each snapshot lives (`agent_workspace_snapshots`): the
bucket, or the pool, the host, the reference, and the digest. The step
that names a host's snapshot carries the digest's hash keyed by the
session, so once the key is revoked nothing confirms what it held. The
run waits for the host's answer a while; one that never comes keeps no
snapshot, and the engine keeps the instance. The runner's sweep keeps
it too: an instance of a session kept by snapshots that no snapshot holds
as it stands is never released, since what its commands wrote outside
its files lives there alone.

**A restore travels with its prepare.** The restore is decided before
any host is asked. For a session inside its tenant's wall, the record
must name a host's store of its pool, or the workspace is lost: a
snapshot of the bucket never crosses into the wall, and one inside the
wall never restores outside it. The prepare carries the reference, the
digest, the size, and the host that kept it. It goes on the lane of the
host that holds the workspace while that host is not revoked, online or
not, which replaces it whole, or on the pool's lane when none does; the
host that restores it holds it. The host starts the workspace once the
bytes match their digest. A host whose store lacks the bytes answers the
restore lost. On the holder's lane, or once no live host of the pool kept
the snapshot, the restore fails, and the loop parks for a person, as the
engine's lost restore does; on the pool's lane, while the host that kept
it is live, another host is asked.

**A restored tree stands.** A prepare that restored brings nothing of
the session's branch over the tree: no sync, no cut, no check that would
park it as diverged. A person who takes control of a workspace kept by
snapshots, which a host holds, gets the workspace the latest snapshot
holds, as the next run would, before the workspace is handed over: a
take whose restore does not land in time hands nothing over, and a take
of a workspace a person holds already restores nothing over their work.

**A refusal for good ends the loop.** A provider's refusal of what a
prepare asks beyond its isolation (to keep it by snapshots, to start it
from a base, or from a snapshot) is final, and the loop ends with its
reason. Every other refusal still clears, since another host may give
the isolation later.

**A hosted base is its host's to build.** A session inside its
tenant's wall whose pin names a base starts from the base the host that
prepares it builds and keeps in its own store
([ADR
2051](2051-an-agent-projects-workspace-base-is-built-once-where-its-workspaces-run.md)).

**A host advertises what it probed.** A host advertises
`snapshot.<level>` only when that level's probe passed, a provider of its
own snapshots a workspace there whole, and its store takes a snapshot
and gives it back. The host's container provider does; a directory's
commands write outside it, so its provider takes none. A session kept by
snapshots and pinned to a pool with no live host that advertises its
level waits on the resource, with the reason, and the host that never
probed it refuses its prepare.

**A snapshot goes with its content.** A revoked key, the sweep's past
the content's life or a person's, takes the session's snapshots out of
the bucket, asks each host that keeps one to erase it, and forgets their
records. A session's purge does the same, with no key revoked: each
host that keeps one is asked to erase it before the records go.

**A container snapshot holds only its own.** The container provider
snapshots a container only when its deployment, workspace, and tenant
labels name it, so a deployment never takes another's container on a
shared Docker.

## Consequences

- One migration: the pin's `durability` and `base`, an agent project's
  `workspace_snapshots`, and the `workspace_snapshots` table.
- A host's snapshots are not sealed: no key of the platform's crosses
  into the wall. They are the tenant's bytes on the tenant's machine, as
  the workspace's files are, and the revocation erases them.
- Hosts of a pool reach one another's snapshots only through a store
  they share. Once the host that kept a snapshot is revoked, the first
  host of the pool that claims its restore makes it from a shared store,
  or answers it lost. A session whose holder is offline waits for it,
  even when another host shares its store.
- A workspace a host holds warm is still restored at its next loop, from
  the snapshot taken of it. A restore that takes longer than its wait
  parks the loop on the resource, and the next run asks for it again.
- A session's purge asks no host to destroy the workspace it holds, its
  files included. The trigger to ask is a host's disk that its purged
  sessions' workspaces outgrow.
- A kept session's instance that no snapshot holds stays until a run's
  end snapshots it, or the session is purged.
- A product's kind kept by snapshots on a bare host waits until a host
  whose provider snapshots a directory joins its pool.
