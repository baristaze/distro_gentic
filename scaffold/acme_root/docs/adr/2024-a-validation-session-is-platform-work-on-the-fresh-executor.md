# ADR 2024: A validation session is platform work on the fresh executor

**Status**: accepted (2026-10-03)

## Context

The spec's Evidence and Agents a Platform Ships have a validation
session run a delivery's checks on a fresh executor, never in the
agent's workspace, with no agent at all, and write the execution record
every run is.

The executor port has a loud null and nothing else, so no delivery's
checks run and the result gate confirms no success. A validation session
is a record of its own that calls no model, but its work goes to a
claimant outside the platform, on its group's lane
([ADR 2013](2013-a-validation-session-is-a-claimants-work-with-a-record-of-its-own.md)),
so the platform's evidence waits on a domain it does not hold.

## Decision

**The platform's executor is an instance of its own workspaces.** Each
run gets an instance under an id nobody used, made by the provider the
process holds, isolated as a container with no egress, and reached by the
transport the platform's processes hold. The platform reads the tree
from the project's repository, outside every workspace, with the
project's fetch credential: the delivered commit, with every path a
protected pattern matches taken from the protected source, whatever the
delivered commit holds there. It is written in as files, with no
credential and no history. Each check's command template runs with
`{version}` and `{out}` filled, under the environment of the instance's
image and its transport. Each trial's results stream is read back within
the run's bound, and the executor hashes what it read. A trial that
crashes, runs past its time, or writes no run it can read is an errored
run, so every trial counts. The instance and its command records are
destroyed when the run ends, whatever ended it.

Outside `local`, every root wires this executor in place of the loud
null. `local` keeps the loud null unless its process hands one in.

**A session pinned inside its tenant's wall runs its checks on a host of
its pool.** They never run on the platform's machines, nor in the
session's own workspace. The run asks the session's pool for a new
instance under its own id, as a prepare is asked, and the instance
carries the session: its pool routes it, and its project is what the
host's owner holds its work to. Its binding names the session. It is made
to the isolation the session is pinned to, its level, its egress, and its
limits: its pool gives that, where a cloud executor's container with no
egress may be beyond a pool of bare directories, and a pinned project's
checks may need what its pool is pinned for. The tree is written in, the
checks run, and the results stream is read back, each as `exec` work,
and the executor hashes what it read. A trial's stream is read in one
item, whose result crosses the wall whole: a stream longer than one
carries is read no further, never waited on, and its trial is an errored
run that names that bound. When the run ends, whatever ended it, the
holding host is asked to purge the instance, or the prepare that waits
is ended, and the relay's rows of the instance go at once. A root that
reaches no pool refuses the run, loudly (`Unavailable`), never a run
elsewhere.

**A validation session is platform work.** It names its project, a check
its project's policy declares, the delivered commit it runs at, and the
base its checks, fixtures, and runner come from. Starting one writes it
and asks for one `VALIDATION` item on the platform's own lane in the same
commit. The maintenance worker claims it and runs the check through the
evidence namespace on the executor. Finishing the session names the
execution record the run wrote, the record every run is. A session runs
its check once: a run kept before a crash is answered again, never run
again.

## Consequences

- No path of a validation session asks for a loop, so no runner claims
  it and no model is called.
- No domain's lane, kind, or claimant is in its path: its item is the
  platform's own, on the platform's own lane, and the maintenance worker
  claims it.
- A session's group, its check's own version, and its parameters leave
  the mapping now and the table a release later
  ([ADR 0038](0038-a-dead-column-leaves-the-mapping-before-the-table.md)).
  A row the previous release wrote keeps its group until then.
- A check its project's policy does not declare fails its work for good.
  An instance that could not be made, or a repository that could not be
  read, is tried again.
- Each validation costs an instance: made, written in, run, and
  destroyed. A pinned session's validation waits, within the run's setup
  bound, on a host of its pool making one; a pool that makes none in
  time fails the run as `Unavailable`.
- An instance's commands and their output are sealed under a key of the
  instance's own, as a session's are under its key, and go with the
  relay's rows when the run ends.
- A host still making the instance when its run gives up binds it after
  the run, and no run purges it: an empty instance, with no tree written
  in, stays on that host until its owner removes it.
