# ADR 2005: A workspace no host can give parks the loop, and a lost one waits for a person

**Status**: accepted (2026-10-03)

## Context

A session's isolation is pinned when it is created, and the host that
prepares its workspace enforces it. The engine already refuses a spec
its provider cannot meet before the loop's first model call, and never
falls back to something weaker. It then ended the loop `errored`.

On the platform a refusal usually means "not now". The session's pool may
have no host online, or none that offers the pinned level, or one that
runs as many directory sessions as its owner allows. Ending the loop
throws away a session that would run once a host can give it.

A workspace is also a cache. Its branch and its commits live on the
remote, so a prepare rebuilds the checkout from there. Sometimes what it
is rebuilt from is gone, and nothing says why. Rebuilding from the
default branch then would restart the work silently, and ending the loop
would throw away what it reached when a person could say what comes
next.

## Decision

**A refused workspace parks the loop on `resource`.** The loop parks
with the unlock `workspace` and a retry time its options set, before any
model call. At the retry time the next run asks again. No weaker
workspace is made, and nothing is spent while it waits.

**A lost workspace parks the loop for a person.** A layer that prepares
a workspace raises `WorkspaceLost` when its durable state is gone and
nothing says why, such as a branch the remote held and lost with no
merged or closed pull request behind it, or one that moved on both
sides. The loop parks on `person` with the unlock `workspace`, loudly,
before any call, and keeps everything it reached. A person restores the
branch, or settles its pull request, and resumes it.

**What changed is told before the first call.** A prepared workspace
carries what changed under the model since its last loop
(`Workspace.changed`): a snapshot of work the last loop left, or a branch
rebuilt after its pull request closed. The loop writes it as an
`environment_changed` step before its first model call.

**The pin is held above the engine.** The platform decorates the
engine's sessions manager, which pins each session as it is created, and
its tools manager, which prepares every workspace to the pin, refuses
what this host cannot give before its provider is reached, brings the
checkout up to the session's branch, and pushes what a workspace holds
before its instance goes. In `local`, the developer's own machine, the
provider's own refusals stand alone, as the twin's level is `local`'s
alone.

## Consequences

- A session pinned to a level no host offers waits, parked on
  `resource`, and costs a claim and a refusal at each retry. It never
  runs on less.
- A loop parked for a workspace resumes at its retry time. Nothing wakes
  it sooner yet, such as a host coming online.
- A release whose push does not land keeps the instance and its work,
  and the loop's release logs it; the next release tries again.
- A session with no pin, made before pins or by a process that does not
  declare its kind, is pinned at its first prepare that asks for a
  workspace, to what that loop asks, and held to it from then on.
- The snapshot and the checkout run in the workspace through the
  transport, under the epoch of the run that holds the session, with the
  workspace's own credentials.
- The evidence's work product is the session's branch as its bound
  repository holds it, fetched into a fresh repository of the platform's
  own, in place of the loud null; the checkout of the workspace this
  process holds tells only what was not delivered. A session whose
  workspace this process does not hold, or whose project binds no
  repository, is still read as nothing, and counts no success.
- The engine's loop gains the two parks and the told change, and its
  workspace interface gains `changed` and `WorkspaceLost`. The next move
  of the base merges over all four.
