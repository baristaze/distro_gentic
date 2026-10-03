# Relay

How a tool call reaches a workspace inside a tenant's own wall. This is
one of the kinds of thing [Acme is made of](../../../../README.md).

A session pinned to a [host pool](../hosts/README.md) runs its tools on
the host that holds its workspace. The agent's loop still runs in the
platform's cloud. Each call crosses the wall as `exec`
[work](../work/README.md), which the host claims, runs, and answers.

## What it holds

- **An exec item**: one operation of one tool call, a command or a file
  operation, for the host that holds the session's workspace. Its id
  comes from the call's idempotency key, so the same call sent again
  finds it. It keeps the call's effect, its deadline, the writer epoch of
  the run that sent it, and the session's isolation. What it runs is the
  session's content, sealed under the session's key.
- **Its result**: how the command ended, kept under the call's key, and
  what it printed, sealed the same way.
- **Its output parts**: what the command printed, a part at a time, as
  the host sent it.
- **A control message**: a stop for an item a host holds: a cancel, an
  interrupt, a deadline cut, or a revoked lease.
- **A workspace binding**: the host that holds a session's workspace,
  and where on it.
- **A prepare**: `workspace` work on the lane of the session's pool,
  asking any host of the pool to make the session's workspace to its
  pinned isolation.
- **A release**: `workspace` work on the lane of the host that holds the
  session's workspace, asking it to let the instance go and keep its
  files.

## What can happen

- **Prepare.** A loop of a pinned session whose workspace no live host
  holds asks its pool for one, and waits on the resource before any model
  call. One ask waits at a time. The host that claims it makes the
  workspace and answers where it is, which binds the session to it. A
  host that answers second, while the first holds it, lets its own go.
  One that cannot make it hands the ask back to the pool after a wait.
  A session whose host is offline waits for it; one whose host was
  revoked asks the pool again.
- **Release.** The runner's sweep finds a workspace a host holds that no
  run accounts for past its grace, among the bindings. It pushes the
  checkout's work through the relay first, then asks the holding host,
  while that host is live and online, to let the instance go. One release
  waits at a time. Only that host answers it, and its answer completes
  the work. A release that waits when a prepare is asked is ended, since
  no live host is left holding the workspace.
- **Send.** The runner's transport sends each operation of a call. A new
  one goes on the lane of the host that holds the workspace. One the
  call sent before is met as it stands, so a run that resumes after a
  crash attaches to the first execution or reads its result.
- **Claim and run.** The host claims the item under a lease, reads what
  it runs, runs it through its own transport, streams the output back,
  and pushes the result. It renews the lease while the command runs.
- **Stop.** A stop is written as a control message and reaches the host
  over its control stream at once. An item no host took yet never runs.
- **Lose the lease.** An unsafe item whose lease runs out ends
  `interrupted`, outcome unknown, and is never run again. A repeatable one
  goes back to the lane of the same host, the one that holds the
  workspace.
- **Purge.** A purged session's items, output, controls, and binding go
  with it, and a deleted tenant's go with the tenant.

## The rules

- **The platform never calls in.** Every exchange with a host is a
  request the host opens, its control stream included.
- **An unsafe call runs once.** Its queue row is claimed once, and a
  claim that finds it started before ends it `interrupted`.
- **A stale writer acts on nothing.** A command, a stop, or a recovery
  from a run below the session's writer epoch is refused, and a command
  a lost run sent is refused at its claim.
- **What crosses is checked.** A part or a result whose bytes do not
  match the hash the host declared is refused before it is read.
- **The first settlement wins.** A result for an item a stop, its lease,
  or the sweep already settled lands nothing.
- **Every row belongs to one org.**

<!-- agents-only
The runner's transport is `impl/transport.TransportRelayImpl`, behind
`TransportPlacedImpl`, which picks it per session by trust's
`PlacementInterface`; the session runner wires both through
`build_managers(transport_layer=...)`. `impl/placement.PlacementRelayedImpl`
answers trust's executor with the bound host, and
`PlacementClaimsRelayedImpl` wraps placement's `claim_for` so a claimed
`EXEC` row reaches a host only after `start`. An unsafe item's row takes
`max_attempts` 1, so the queue's own sweep fails it, never requeues it;
`settle_expired` writes the `interrupted` result and the revoke. The
engine's file operations carry no call key, so each is an item keyed by
itself. ADR 2004 records the decisions.
-->

## How another namespace composes it

The session runner puts the relay behind the engine's transport for a
session inside a wall, and the engine sees one transport either way. The
gateway serves the host's calls and its control stream. The maintenance
worker settles items whose lease ran out and purges a tenant's rows. The
runner's tools find a pinned session's workspace on its host
(`impl/workspaces.PlacedWorkspacesRelayedImpl`), and the host's answer to a
prepare binds it with `bind_workspace` (`prepared`). The runner's sweep
reads the bindings (`bindings`), reaches a holding host through `holder`,
and asks it to let an instance go with `ask_release`; the host answers
with `released`.
