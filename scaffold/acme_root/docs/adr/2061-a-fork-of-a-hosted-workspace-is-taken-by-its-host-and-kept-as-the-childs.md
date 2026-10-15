# ADR 2061: A fork of a hosted workspace is taken by its host and kept as the child's

**Status**: accepted (2026-10-13)

## Context

The engine's fork takes the parent's workspace as it stands at the
spawn, through the run that holds it, and keeps the child's copy sealed
in the platform's bucket
([ADR 1030](1030-a-fork-starts-from-its-parents-workspace-as-it-stands-at-the-spawn.md)).
It takes the snapshot through the provider of the process that runs the
loop. A workspace on a customer's host is made and run by that host, so
that provider holds nothing to take, and the spawn was refused. A hosted
agent could not try a hypothesis on a copy of its own tree.

A host already snapshots the workspace it holds at a run's end, and
keeps the bytes in its own store, inside the wall
([ADR 2050](2050-a-snapshot-lives-on-its-workspaces-side-of-the-wall.md)).
The fork reuses that path.

## Decision

**The host takes it at the spawn.** A spawn that forks a workspace a
host holds asks that host for a `snapshot`, through the exec relay, as a
run's end does. The host takes back what its broker attached, takes the
live instance whole, scans it for the tenant's secrets, and keeps it in
its own store. The engine's tools ask the platform for a fork point
first, and take the workspace through their own provider only when the
platform answers none.

**Kept as the child's.** The snapshot item names the child it is kept
for. The child's id is the spawning call's, so it is known before the
child is made. The host keeps the copy in the child's place in its
store, where no erase of the parent's snapshots reaches it. The exec
relay records the host's answer under the parent, since the child does
not exist yet. Once the child is made, its copy is recorded as its own:
where the host keeps it, and its digest keyed by the child. The child's
restore names that record, and its first prepare restores the copy on a
host of the pool whose store keeps it, as any restore does.

**The parent keeps nothing of it.** The engine keeps the fork's
snapshot as the parent's own too, when the parent is kept by snapshots.
A hosted parent keeps none: one take, one copy, the child's. The
parent's next run end keeps its own, as it always does.

**Refused before anything is spent.** A session that keeps no content at
rest is refused before any host is asked. With no live host that holds
the workspace, or a host that takes no snapshot of it, the fork is
refused with the reason, before the tree's slot is taken or the child is
made. A workspace on a VM of the cloud pool is still taken through
the engine's provider, which refuses it: the pool keeps the VM's
whole disk, and its host takes no snapshot.

## Consequences

- No new table and no migration: the payload of a `snapshot` item names
  the child, and the host keeps the copy under it.
- The take's record stays under the parent, unnamed by any step, until
  the parent's erase or purge forgets it. The bytes it points at are the
  child's, and only the child's erase takes them.
- A spawn refused after the take, by a race for the tree's last slot,
  leaves the copy in the host's store under a child that is never made.
- A host older than this release ignores the child it is told and keeps
  the copy in the parent's place. The child still starts from it, but
  the parent's erase takes it, and the child's erase does not.
- A rewind of a hosted parent cannot name the state its child started
  from. The trigger to keep a second copy is a person asking for that
  rewind.
