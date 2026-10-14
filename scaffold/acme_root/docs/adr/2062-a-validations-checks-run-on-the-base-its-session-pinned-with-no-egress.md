# ADR 2062: A validation's checks run on the base its session pinned, with no egress

**Status**: accepted (2026-10-13)

## Context

A session of a kind that takes its project's workspace base pins that
workspace base as its base and works on it
([ADR 2051](2051-a-projects-workspace-base-is-built-once-where-its-workspaces-run.md)).
The fresh executor ran its checks elsewhere: in the cloud, on an
instance of the executor's own image
([ADR 2024](2024-a-validation-session-is-platform-work-on-the-fresh-executor.md)).
Nothing the setup installed was there, so a check that imports it
failed, and the result gate refused a success the work earned. A
project names a workspace base because its work needs it, and its checks
need it too.

## Decision

**The checks' instance starts from the session's base.** The executor
reads the session's pin, its base included, for every session. In the
cloud, the instance is made at the executor's own isolation and limits,
on the pinned base: its image, and the tenant's snapshot of its setup,
read where it is kept or built once, as a session's prepare reads it.
Inside the wall, the host of the pool that makes the instance builds the
base, or reads it from its own store, as it does for a session's
workspace.

**It is never the session's workspace.** The instance is new, under an
id of its own. It starts from the base's snapshot, which holds what the
setup wrote and nothing of a session's, never from a snapshot of the
session's work. The delivered tree is written in as before, so the head
reaches the checks through that tree alone.

**Its egress is none.** The setup's egress is its build's alone. In the
cloud, every instance holds no egress, on a base or not. Inside the
wall, an instance on a base asks for no egress, whatever the session
holds. One with no base is made to the session's isolation whole, as
before, since a pool of bare directories holds no closed egress.

**The record names the base's image.** The run's record names the image
the instance started on: the base's, when the session pinned one. The
host stays the cloud's or the pool's.

**A base with setup is never skipped.** A process that pins a base with
setup and reads no base refuses the checks before anything runs. It
never runs them on the bare image.

## Consequences

- No migration: the pin already carries the base.
- In the cloud, the base is keyed by the executor's isolation level. A
  session at the same level shares its build. One at another level has
  it built once more, at its first validation.
- A pool whose hosts hold no closed egress at the session's level makes
  no instance for a session on a base, and its checks are refused.
