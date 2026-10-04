# ADR 2022: A repository's credentials are the platform's, and the agent never holds one

**Status**: accepted (2026-10-03)

## Context

The spec holds that a workspace never holds a platform credential
(Trust), and that the one credential the platform issues a host is a
push token minted per session, short-lived and scoped to the session's
branch, never the integration's own (Workspace Hosts). The Result Gate
reads what a session delivered from the repository its project binds, so
a private repository needs a credential where that read runs. The
engineer delivers through its branch and its pull request, so something
has to write them. An agent's workspace runs what a model wrote:
whatever it holds, a model can print, send, or push with.

## Decision

**A fetch credential per project, in the tenant's store.** A person who
manages the tenant's members gives a project's repository one read-only
credential, a user name and a password or token. Its value goes to the
tenant's secret store under the project. The workspaces keep a record
beside it, one row a project, saying only who gave it and when. A later
one replaces it.

**The reader resolves it, outside every workspace.** The read of a
session's work product takes the credential from the store and hands it
to its own git through the environment of the commands that ask the
repository, as a header for the repository's URL alone. It is never on a
command line, in a file, in a message, or in a workspace.

**A push token per loop, checked by the platform.** The engineer's
`open_pull_request` tool asks the workspaces for a token, minted for the
session's branch on its project's repository. Only its digest is kept,
on the session's workspace, with its expiry. It ends when its lifetime
passes, when the loop's workspace is prepared again or released, or when
a newer one is minted. The platform checks it before each write: it
writes the session's own branch, its snapshots, and its pull request,
and nothing else.

**The forge writes with its own credential.** Once the token is checked,
the forge integration points the branch at the workspace's committed
head and opens the pull request. The integration's credential never
leaves it. The model writes the title and the body alone; the branch,
the repository, and the base are the platform's records.

## Consequences

- A private repository's delivery is read once its project has a fetch
  credential, and reads as unavailable without one. The result gate
  then fails closed.
- No credential a model could reach outlives its loop. A token taken
  from a tool's call is refused once its loop's workspace goes.
- The tenant's purge takes each value out of the store before its
  record, so no value is left behind a record that is gone.
- A tenant with no forge connected opens no pull request: every write
  is unavailable, and the engineer's tool says so.
