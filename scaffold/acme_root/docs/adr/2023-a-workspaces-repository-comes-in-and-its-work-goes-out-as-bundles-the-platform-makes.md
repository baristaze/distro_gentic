# ADR 2023: A workspace's repository comes in, and its work goes out, as bundles the platform makes

**Status**: accepted (2026-10-03)

## Context

ADR 2022 keeps every repository credential out of a workspace: the
platform reads a private repository with the project's fetch credential,
and the forge writes with its own. Two paths would still run through the
workspace itself. A checkout that fetches the bound repository from
inside has no credential, so a private repository never checks out. A
forge handed a commit id that exists only in the workspace has nothing
that carries the commits to the repository, and a snapshot pushed from
inside has the same fault. The engineer's workspace also has no egress,
so whatever reaches the repository is done by the platform, outside it.

## Decision

**In: a bundle the platform reads.** Before a loop, the platform fetches
the default branch, the session's branch where the repository holds it,
and its last snapshot where the repository never held the branch, with
the tags in their history, on its own host, with the project's
fetch credential, as the read of a delivery does. It reads only where a
workspace may reach: it resolves the repository's host first, refuses it
when any address is in the networks no workspace reaches, holds git to
those addresses, and follows no redirect. It hands the workspace a git
bundle of them through the transport's files. The checkout fetches from that bundle and from
nothing else. A cut starts from that snapshot when it came, and from the
default branch as the bundle brought it otherwise.

**Out: a bundle the platform makes.** When the engineer opens its pull
request, the platform checks the push token, then makes a bundle in the
workspace of the committed head and the commits the repository lacks,
and reads it back. Source control pushes that one head to the session's
branch, with the integration's own credential. Nothing else in the
bundle is written: not another branch, not a tag. A release's snapshot
goes the same way, to its snapshot ref.

**Forward only.** The forge never forces a ref. A session's branch only
moves forward, so no commit on it is lost, a person's included. The
engineer is told so: a fix is a new commit on top, never an amend or a
rebase, and a refused move says the same.

**The head is on the branch before it is validated.** Validation reads
the delivered head from the repository, never from the workspace, which
the agent can write. So the engineer opens its pull request first, and
then validates. A validation of work the branch does not hold is refused,
and says to open the pull request.

## Consequences

- The checkout cannot reach the repository on its own, so a private
  repository checks out, and its session delivers, with no credential in
  the workspace.
- With no forge connected, a snapshot cannot be pushed: a release with
  work left keeps its instance, as a release whose push fails does.
- Each checkout carries the default branch's whole history, read again
  on each loop. A bundle against what the workspace already holds waits
  until an attach's bundle passes a tenth of its bound, 51 MB by default.
- The local stack's twin forge pushes for real, with a repository's
  credential where it is given one, so the next loop finds the branch and
  the snapshots, and the local stack shows the whole path.
