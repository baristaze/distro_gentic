# Workspaces

Group id: `workspaces`. Covers Workspaces and Isolation of
`distro_gentic_spec.md`.

This group judges the workspace a session's tools work on: its life as a
cache, what happens to its work before it goes, its isolation level and
how that level is pinned, probed, and refused, and its egress. It leaves
the isolation modes a host advertises and the ceilings its owner sets to
`placement`, a person's commands in a workspace to `watch`, the
untrusted mark and the rule of two to `wall`, and the sweep that purges
an unclaimed instance to `fleet`.

## WSP-01 A workspace is a cache, and an idle session holds no machine

**Principle.** A workspace is the checkout the tools work on: a session
branch, inside the instance a host prepared. The branch, its commits,
and the artifacts live elsewhere. After a loop, the instance stays warm
for a short grace so a follow-up can reattach; then it is released. It
is released at once when the session is archived or cancelled. A session
that merely exists holds no machine.

**Source.** Workspaces and Isolation, A Workspace Is a Cache.

**Look for.** The instance's lifecycle: what holds it after a loop
ends, the grace, and the release on archive and on cancel; anything kept
only in the workspace.

**Violation.** An instance kept after a loop ends and its grace runs
out, or kept after the session is archived or cancelled; a commit or an
artifact whose only copy is in the workspace. (A loop parked on a
hand-over has not ended: taking control keeps the workspace, as WAT-05
says.)

**Severity.** medium

**Check.** review

## WSP-02 Work is pushed before release, and nothing restarts silently

**Principle.** Before an instance is released, uncommitted work is
committed to a snapshot ref and pushed, and the next loop is told about
it. When a session's branch has vanished, the platform rebuilds it only
when it knows why (a merged or closed pull request). Anything else fails
loudly; nothing restarts silently from the default branch.

**Source.** Workspaces and Isolation, A Workspace Is a Cache.

**Look for.** The release path and what it does with uncommitted work;
what the next loop is told of a snapshot; how a missing session branch
is handled.

**Violation.** A release that drops uncommitted work, or commits it
without pushing; a snapshot the next loop is not told about; a vanished
branch rebuilt from the default branch without a known reason.

**Severity.** medium

**Check.** review

## WSP-03 A level separates what its row says, and a twin only plays

**Principle.** A session's isolation is one of four levels. A microVM or
VM per session separates filesystem, processes, network, and kernel,
across sessions and tenants; it is the cloud's level. A container per
session separates processes and filesystem, and shares the host kernel
unless a user-space kernel stands between. A directory on the host
separates only what a dedicated user and the directory separate. A twin
separates nothing: it plays the lifecycle for tests, says so, and runs
in `local` only.

**Source.** Workspaces and Isolation, Isolation Levels.

**Look for.** The isolation levels the platform defines and what each
says it separates; where a twin level may be chosen.

**Violation.** A level described or advertised as separating more than
its row (a container said to separate the kernel with no user-space
kernel between); a twin chosen outside `local`, or one that does not say
it is a twin.

**Severity.** high

**Check.** review

## WSP-04 Isolation is pinned, and a host that cannot provide it refuses

**Principle.** A session's isolation is pinned when it is created and
enforced by the host. A host that cannot provide it refuses the
`workspace` work before the loop's first model call, and the loop parks
on `resource` until a host in its placement can. Isolation is never
weakened.

**Source.** Workspaces and Isolation, Pinned, Probed, Refused.

**Look for.** Where a session's isolation is set, and whether anything
changes it later; what a host does with `workspace` work whose isolation
it cannot provide; when in the loop that refusal comes.

**Violation.** Isolation chosen per loop or per host rather than pinned
at creation; a host that prepares a weaker level than the pinned one; a
refusal after the loop's first model call; a refused session that fails
instead of parking on `resource`.

**Severity.** high

**Check.** review

## WSP-05 Every level runs stripped of platform credentials

**Principle.** Every isolation level runs from a process environment
stripped of every platform credential.

**Source.** Workspaces and Isolation, Pinned, Probed, Refused.

**Look for.** How a workspace process's environment is built, at each
level; what the host's or the runner's environment holds that a child
process could inherit.

**Violation.** A workspace process that inherits the host's or the
runner's environment; a platform credential, the host's own among them,
visible to a workspace process at any level.

**Severity.** high

**Check.** review

## WSP-06 The cloud never runs a session on a shared host

**Principle.** The cloud never runs a session directly on a shared host,
and a bare directory exists only inside a customer's wall.

**Source.** Workspaces and Isolation, Pinned, Probed, Refused.

**Look for.** The isolation levels the cloud pool offers; where a
directory level may be chosen.

**Violation.** A cloud workspace that is a directory or a bare process
on a shared host; a directory level offered by the cloud pool.

**Severity.** high

**Check.** review

## WSP-07 A bare directory runs as a dedicated user, or the host refuses

**Principle.** A bare-directory workspace runs as a dedicated,
unprivileged user that cannot read the host's credential, its secret
store, or another workspace. A host that cannot enforce the session's
egress for that user refuses the session, as it refuses any isolation it
cannot provide.

**Source.** Workspaces and Isolation, Pinned, Probed, Refused.

**Look for.** The user a directory workspace runs as, and what it can
read; the egress check before a directory session is accepted.

**Violation.** A directory workspace run as the host's own user, as an
administrator, or as a user another workspace shares; a host credential,
secret store, or other workspace that user can read; a directory
session accepted where the host cannot enforce its egress.

**Severity.** high

**Check.** review

## WSP-08 Concurrency follows isolation

**Principle.** Concurrency follows isolation: a host that offers only a
bare directory runs one session at a time, unless its owner says
otherwise.

**Source.** Workspaces and Isolation, Pinned, Probed, Refused.

**Look for.** How many sessions a host accepts at once, and what sets
that number.

**Violation.** A host that offers only a bare directory and runs several
sessions at once without its owner's setting; a number set only in the
control plane, instead of by the owner on the host.

**Severity.** high

**Check.** review

## WSP-09 Egress is an allowlist of destinations and methods

**Principle.** A workspace's egress opens outward only, to a per-project
allowlist that names destinations and methods: source control, through a
credential scoped to the session's branch; package registries,
read-only, through a vetting mirror; and the platform's endpoints. Open
egress is an explicit policy choice, recorded.

**Source.** Workspaces and Isolation, Egress.

**Look for.** Where a workspace's egress is enforced and the allowlist it
reads; how source control and registries are reached; how open egress is
chosen and recorded.

**Violation.** Egress open by default, or an allowlist of destinations
with no methods; source control reached with a credential wider than the
session's branch; a registry reached directly or with a write method;
open egress with no recorded policy choice; a connection opened from
outside into a workspace inside a customer's wall.

**Severity.** high

**Check.** review

## WSP-10 A workspace never reaches the platform's insides

**Principle.** A workspace never reaches the platform's internal network
or a cloud metadata endpoint.

**Source.** Workspaces and Isolation, Egress.

**Look for.** The network rules of each isolation level; the routes from
a workspace to internal addresses and metadata addresses.

**Violation.** A workspace that can open a connection to an internal
service or a cloud metadata address, by allowlist, by route, or through
a proxy.

**Severity.** high

**Check.** review

## WSP-11 No surface fetches a URL from agent output

**Principle.** No surface renders a URL from agent output as a fetch,
such as an image in a comment or a mirror.

**Source.** Workspaces and Isolation, Egress.

**Look for.** Every surface that renders agent output (the portal, the
comments the agent writes, mirrors, notifications), and how each renders
an image or a link.

**Violation.** A Markdown image, a link preview, an unfurl, or a proxy
that fetches a URL the agent wrote.

**Severity.** high

**Check.** review
