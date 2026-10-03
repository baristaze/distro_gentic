# ADR 2024: A validation session is platform work on the fresh executor

**Status**: accepted (2026-10-03)

## Context

Evidence: "Validation never runs in the agent's workspace. It runs on a
fresh executor, from the delivered commit, with the checks, fixtures,
and runner taken from the protected source, under an environment the
agent did not set. The executor writes and hashes the results." The
Agents a Platform Ships: "A validation session runs a delivery's checks
with no agent at all, on a fresh executor (a workspace nobody used,
never the agent's), on the same queue, and writes the same execution
record."

The executor port has a loud null and nothing else, so no delivery's
checks run and the result gate confirms no success. A validation session
is a record of its own that calls no model, as it should be, but its
work goes to a lab's lane for a daemon to run
([ADR 2013](2013-a-validation-session-is-station-work-with-a-record-of-its-own.md)):
the platform's evidence waits on a domain it does not hold.

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
the run's bound, and the executor hashes what it read. The instance and
its command records are destroyed when the run ends, whatever ended it.

Outside `local`, every root wires this executor in place of the loud
null. `local` keeps the loud null unless its process hands one in.

**A session pinned inside its tenant's wall is refused.** Its checks
never run on the platform's machines, and its pool's host binds one
workspace to a session, so it has no instance to give a run. The refusal
is loud (`Unavailable`), never a run elsewhere.

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
- No lab, station, or daemon is in its path. Placement has no lab's lane
  and the work queue no station kind; a claimant through the gateway is
  a host.
- A session's lab, its check's own version, and its parameters leave the
  mapping now and the table a release later
  ([ADR 0038](0038-a-dead-column-leaves-the-mapping-before-the-table.md)).
  A row the previous release wrote keeps its lab until then.
- A check its project's policy does not declare fails its work for good.
  An instance that could not be made, or a repository that could not be
  read, is tried again.
- Each validation costs an instance: made, written in, run, and
  destroyed. A pinned session's validation waits on its pool's host
  making an instance per run.
