# ADR 2051: A project's workspace base is built once where its workspaces run

**Status**: accepted (2026-10-11)

## Context

The software engineer works in a container with no egress. It cannot
install a package its work needs, and open egress would make every
command after its first tool result act outward and wait for a person.
The engine keeps a workspace base, an image and its setup built once for
a tenant and kept as a snapshot
([ADR 1028](1028-a-workspace-base-is-built-once-for-its-tenant-and-kept-as-a-snapshot.md)),
and the pin carries a kind's base
([ADR 2050](2050-a-snapshot-lives-on-its-workspaces-side-of-the-wall.md)).
What a session needs installed is its project's, not its kind's, and a
customer's host built no base, so a session inside the wall whose pin
named one was refused for good.

## Decision

**A project names its workspace base.** A project's workspace base is an
image, its setup commands, and the package registries the setup
reaches. Whoever writes the tenant's configuration sets it or takes it
away (`PUT` and `DELETE /projects/{id}/workspace-base`), as it creates the
project. Its image starts with a letter or a digit, so a runtime never
reads it as an option.

**A kind takes it from a version that says so.** The platform names the
kinds that take their project's workspace base by name and version
(`WORKSPACE_BASE_KINDS`): the software engineer from version 8, which
also tells its model that its workspace has no network and a missing
package is named in its result. When such a session is created, its pin
takes the base the workspace base names in place of its kind's own. A
kind that takes none, a project that names none, and a session of no
project pin what they pinned before. A product names its own kinds that
take it the same way, by name and version, in its slot
(`ProductKinds.workspace_bases`), and never one of the platform's.

**A session keeps the base it pinned.** The pin is read once. A changed
workspace base is another base, keyed by its own hash, so the next session
builds it, and a session already running keeps starting from the base
it started on.

**The setup's egress is the project's recorded choice.** A setup that
names a registry runs with open egress, since a setup's egress is open
or none; one that names none reaches nothing. The registries are the
record of why. A workspace on the workspace base keeps its kind's egress:
the software engineer's is none. Holding a setup to its registries alone
waits on the egress proxy, as the engine's base does.

**It is built where its workspaces run.** In the cloud, the runner's
provider builds it through the engine, into the platform's bucket under
the tenant's prefix. On a customer's host, the host builds it with its
own provider and transport and keeps it in its own store, beside its
snapshots, inside the wall: nothing of it reaches the platform. The
build runs beside the prepares, since it outlasts a work item's claim: a
prepare that finds it running waits a while, then is refused with a
refusal that clears, and is asked again. One build serves the project on
a host, and the hosts of a pool that share a store share it. A workspace
on it runs the workspace base's image in place of the host's own, as a
cloud workspace on a base runs the base's image in place of its
provider's. Each command in it prepares it again on the base the host
keeps, so an instance that stopped starts anew from that base. A command
never builds one, since its ceilings hold no setup's egress: a host that
keeps none refuses the command.

**A host's build holds to its owner's ceilings.** A prepare that may
build a base whose setup has open egress asks its host for open egress,
whatever the workspace's own, so an owner who closed egress refuses it
before anything runs. The host builds a base only at a level whose
snapshots its probe showed.

**The setup carries nothing of the platform.** Each command runs as `sh
-c`, with no secret and no variable of its own, and what it printed is
not kept. No model runs. The host's base is scanned for the values of
the secrets the host keeps for the tenant, as a snapshot is, and one
that holds a value is not kept. Setup needs no approval: it runs the
commands a person declared and reads no tenant's record.

**A failed setup keeps nothing, and says why.** In the cloud the engine's
refusal does not clear, and the loop ends with the command's place, its
text, and its exit code. On a host, the host answers the prepare
`unbuilt` with that reason: the work spends an attempt and keeps the
reason, and the loop waits on the resource and says it, since another
host may build the base. A refusal on the wire holds 2,000 characters
and a setup command 4,000, so the host cuts the command's text to fit,
with a marker that says how much it left out, and keeps its place and
its exit code whole. The command keeps its cap: a setup command is
often a long script. A host answers the same failure for ten
minutes, then builds again.

## Consequences

- One migration: the project's `workspace_base`.
- A host whose owner closed egress serves no workspace base whose setup
  reaches a registry, even one its store already holds.
- A rebuild on a schedule is a later step, not an agent automation
  action here: a base is keyed by what it names, so rebuilding the same
  one means dropping it first. The trigger is a workspace base whose
  image or registry moves under a fixed name often enough that a project
  asks.
- Each host of a pool that does not share a store builds its own copy
  the first time a session lands on it.
- A host's build that dies with its process leaves nothing kept, and its
  next prepare builds again.
