# Placement

Where each kind of a session's work runs, and who claims it. This is one
of the kinds of thing [Acme is made of](../../../../README.md).

A session always lives in the platform. To make progress it becomes
[work](../work/README.md), and each kind of work runs where its
environment is.

## What it holds

- **A lane per environment.** Every kind is one queue with one shape;
  the lane says where an item runs:

  | Kind | Lane | Claimed by |
  |---|---|---|
  | `LOOP` | `loop:<plan tier>`, or `loop:org:<org id>` for a tenant with a lane of its own | a session runner, from the queue directly |
  | `EXEC` | `host:<host id>`, the host that holds the workspace | that host, through the gateway |
  | `WORKSPACE` | `pool:<pool id>` to prepare; `host:<host id>` to release or purge | a host of the pool, or the holding host, through the gateway |
  | the platform's own | `default` | the maintenance worker |
  | a product's | where its registered lane reads off its payload | a claimant of its registered kind, through the gateway |

- **A claimant**: a machine outside the platform's processes, as its
  credential says it is: its kind, its id, the tenant whose wall it sits
  in (none for one of the platform's own pool), and its pool. The
  platform's kind is the host; a product registers its own.
- **The kinds' registries** (`kinds.py`): each kind of work with its
  lane and the claimant kind that takes it, and each claimant kind with
  the lanes and kinds its identity claims. The platform's go through them
  as a product's do.
- **A fair share**: each tenant's plan tier, whether its loops run in a
  lane of their own, and how many of them run at once. A tenant with
  none has the default share: the `standard` tier and eight loops.

## What can happen

- **Enqueue.** The work manager asks placement for the lane of every
  item it enqueues, so no producer picks one: a loop goes to its
  tenant's lane, and a kind a host runs to the lane its
  payload names.
- **Claim by a runner.** A session runner serves one loop lane and
  claims from the queue as every worker does.
- **Claim for a claimant.** The control plane claims on its
  behalf, from the lanes its identity names and nothing in its call, and
  only the kinds registered for its kind. A claimant inside one tenant's
  wall is never handed another tenant's item: the item fails for good, a
  dead letter.
- **Answer for a held item.** A product's claimant reads its item, renews
  its lease, and reports it done or failed, only while it holds it, in
  its tenant. Any other item is not found. A report is held to its shape
  first. A host answers through the relay instead.
- **The guard at the claim.** A claimed loop runs only while fewer of
  its tenant's loops run ahead of it than its share allows. Otherwise it
  goes back to its lane for a delay, with no attempt spent.
- **Set a share.** An operator writes a tenant's share, a new version
  each time, and the tenant's stream names the operator. A tenant never
  writes its own.
- **Read a standing.** An operator who names the tenant reads why one
  of its sessions is or is not moving (its park, its loop's item, lease,
  lane, and place in line, its share, and where it runs), and why one of
  its hosts takes no work (its state, what it advertised, and what waits
  on its lanes): ids, counts, times, and states, never what the tenant
  wrote.
- **Count the fleet.** The sweep reads, across every tenant, the parked
  sessions by reason and age, the ready loops by plan tier, and the
  hosts by state, each by bounded labels alone, for the operator
  dashboard.
- **Purge.** A tenant deleted past its retention loses its share.

## The rules

- **A lane is where the environment is.** A kind is claimed only from
  its own lanes, and a claimant's lanes come from its identity.
- **A claimant takes only its own kinds.** A kind is taken only by the
  claimant kind it names, and a claimant kind that names another's kind
  takes none of it.
- **The claim stays the guideline's.** The order within a lane is the
  queue's own; the guard counts the loops claimed under a live lease
  before an item in that order, and every one on another lane, so of
  two loops claimed together the later waits, and neither waits on the
  other forever. A loop whose runner lost its lease no longer counts.
- **Each lane in use has runners of its own.** A plan tier's lane, or a
  tenant's own, is served by runners started on it (`ACME_RUNNER_LANE`).
- **A lost claim writes nothing.** A new claim of the same loop takes
  the next writer epoch, which refuses the lost run's steps.

## How another namespace composes it

A kind a host runs names where it runs in its payload
(`types/work.py`): a host or a pool. A product's kind names it too, and
its registered lane reads it. The gateway resolves a caller's credential
to a `Claimant` and calls `claim_for`, then `held_for`, `extend_for`,
and `report_for` for a product's claimant, each under the claim token
`claim_for` handed it; it never passes a lane or a kind.
