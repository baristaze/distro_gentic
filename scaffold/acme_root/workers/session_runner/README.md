# The session runner

The process that runs the loops of agent sessions. A person's message, an
unlock, or a loop that ends with a message still waiting turns a session
pending, and the write that does it asks for a `LOOP` work item. The runner
claims it and calls the loop's one operation,
[`LoopManagerInterface.run`](../../om/src/acme/om/agents/loop.py), under the
context the claim built: the person who woke the session, on the service
role. Every tool call asks that person's own permissions again
([ADR 1007](../../docs/adr/1007-a-delegated-call-asks-the-persons-permissions-again.md)).

It is a worker role of its own, beside the maintenance worker, and never
inside the API ([ADR 1011](../../docs/adr/1011-a-sessions-loop-runs-in-a-worker-of-its-own.md)).

## How a loop runs here

- **The claim** takes the item under a lease, and the runner renews it
  while the loop runs. It is the maintenance worker's claim loop, taken
  whole: capacity, the renewal and its fence, liveness, and the drain on
  stop. A runner serves one loop lane, a plan tier's or a tenant's own
  ([placement](../../om/src/acme/om/placement/README.md)).
- **The fair share** is the guard a claimed loop meets first: one over
  its tenant's share goes back to its lane for a delay, with no attempt
  spent, and never runs
  ([ADR 2002](../../docs/adr/2002-a-tenants-loops-are-held-at-the-claim-in-the-claim-order.md)).
- **The run** takes the session's next writer epoch before it reads the
  history. A run that lost its claim, to a lease that ran out or to a
  person who took the environment over, can append no step and send no
  command.
- **A run whose time is up** hands its item back at once, with no attempt
  spent, and the next claim goes on with the loop. A run that finds its
  session gone completes the item. One that misses anything else, such as
  a kind this runner does not declare, fails it: it is retried, and past
  its attempts dead-lettered, where an operator requeues it. Any other end
  completes the item.
- **A runner that dies** leaves its item claimed until the lease runs out.
  The next sweep, of any worker, puts it back, and the next run settles
  the calls the lost one left open by their effect: one that only reads or
  is safe to repeat runs again, and one that is not is answered as
  interrupted, never repeated.
- **The sweep** takes back the expired leases and relays the outbox a crash
  left. Then it reads the workspace instances this host holds for its
  deployment (`ACME_WORKSPACE_DEPLOYMENT`). One whose session has no loop
  item queued or claimed is no run's; once a pass finds it so past a
  grace (`ACME_RUNNER_WORKSPACE_GRACE_SECONDS`), it is released the way a
  run releases it, its work pushed to a snapshot ref first. A push that
  does not land keeps it for the next pass. One whose tenant is deleted
  is purged. One whose tenant or session the database holds no record
  of, as after a restore, is left alone and logged. Then it reads every
  workspace a tenant's host holds, by the relay's bindings, and holds
  each to the same proofs. One whose loop is parked on a hand-over is
  the person's, and stays. Past the grace, its work is pushed to a
  snapshot ref through the relay, unless a snapshot after the session's
  last step holds it already, as a loop's end leaves it; only then is its
  host asked to let the instance go. One whose release was asked since
  its session's last loop is not asked again, answered or failed (a
  failed one is logged), one whose host is offline waits for a later
  pass, and a deleted tenant's is left to the tenant's purge. The sweep
  purges no rows: the purges, and the purge login, are the maintenance
  worker's.

The runner holds the model providers' keys and runs tools in the
workspaces its settings name. It holds no purge login. Every call it
runs passes the [trust](../../om/src/acme/om/trust/README.md) layer
first: its audit entry is written with this runner as its executor, and
a call whose secret would cross its session's wall is refused. Then the
gates of the session's [playbooks](../../om/src/acme/om/playbooks/README.md)
hold it, and only narrow what policy let through. A session's first loop
recalls the [knowledge](../../om/src/acme/om/knowledge/README.md) its
subject triggers before its first model call. A call of a session the
tenant's automation principal started runs on that principal's grant
alone ([automations](../../om/src/acme/om/automations/README.md)).

A run that parks on what only a person clears tells whoever can clear it,
on their channels, before its item completes
([notifications](../../om/src/acme/om/notifications/README.md)).

## What a product gives it

The agent kinds and the tools are the product's. A product's own entry
point passes them to `main`, as `tests/e2e_runner.py` passes the suite's,
and its API passes the same kinds, since a session starts on one of them.
Its settings carry the prefix `ACME_RUNNER_` for its own knobs, and read the
rest as every process does (`.env.example`).

`serve` runs the process; `health` asks the running process's `/healthz`.

## Where it runs

Locally it is a host process (`scripts/dev.sh`). In staging and
production it is a service of its own, from
`deployment/docker/session-runner.Dockerfile`, rolled after the API's
migration with a count and a ceiling. There it prepares no workspace: a
session's tools run on a host of its tenant's pool, and a session that
asks the runner for one is refused before its first model call. Its role
reads a tenant's own secrets and writes none, and it reaches no inbound
queue
([ADR 2026](../../docs/adr/2026-the-runner-is-a-cloud-service-with-no-workspace-and-a-host-installs-as-a-user-of-its-own.md)).

## Test

```bash
uv run pytest -q workers/session_runner/tests -m "not integration"
make migrate && uv run pytest -q workers/session_runner/tests -m "integration and not live"
make test-live    # one loop on a live provider; spends, within a budget the case sets
```

The end-to-end suite runs the API in the test's process over the compose
stack and the runner as a process of its own on the scripted model. It
kills a runner with a signal in the middle of a tool call and shows the
next one take the loop over.
