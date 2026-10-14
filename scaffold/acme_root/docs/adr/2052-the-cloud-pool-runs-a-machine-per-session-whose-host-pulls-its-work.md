# ADR 2052: The cloud pool runs a machine per session, whose host pulls its work

**Status**: accepted (2026-10-11)

## Context

The runner is a cloud service that prepares no workspace
([ADR 2026](2026-the-runner-is-a-cloud-service-with-no-workspace-and-a-host-installs-as-a-user-of-its-own.md)):
every tool call of a deployed session needs a host of its tenant's. A
session in the platform's cloud cannot run a command or validate. The spec
names a VM per session as the cloud's level, and the engine gives the
machines it needs: an interface that starts, stops, snapshots, and
destroys a machine by name, on Lima locally
([ADR 1029](1029-a-vm-workspace-is-a-machine-of-its-own-and-its-snapshot-is-its-disk.md)).
A host inside a tenant's wall already prepares a workspace, runs its
calls, and answers them through the exec relay, and a session kept by
snapshots already keeps them on its workspace's side of the wall
([ADR 2050](2050-a-snapshot-lives-on-its-workspaces-side-of-the-wall.md)).

## Decision

**A VM per session is a host per session.** A session of the cloud whose
pinned isolation is a VM runs on a machine of the cloud pool, when the
pool runs machines here: one machine per session, started through the
machines interface. The machine runs the same host program a tenant
installs, from the pool's image (`deployment/machines/`), with Docker
inside. The runner reaches it through the exec relay, as it reaches any
host: the host pulls, and the platform never calls into the machine. Its
commands hold the machine whole, its root through Docker: the machine is
the session's wall.

**The host's credential is the machine's alone.** The pool hands each
machine, as it starts, one seed: where the platform answers, and a
one-use key. Only the key's digest is kept. The machine's host trades the
key once (`POST /v1/hosts/machine-enrollments`) for a host's credential
of the session's pool of one, a pool the platform makes for the session,
which the tenant does not list, place a session on, or issue a token for.
The host carries the session in its identity, and placement fails for
good any item of another session that reaches its lanes, as it fails one
of another tenant. The seed and the host's home sit on the guest's
memory-backed `/run`, so a disk the pool keeps holds neither. The host
holds no database credential, no model key, and no history; a cloud
machine holds no instance role, so its metadata endpoint has no
credential to hand out.

**The cloud's machines are a backend of the same interface.** `ec2` runs
each machine as an instance of the pool's launch template
(`deployment/terraform/modules/cloud_pool`), in a security group by its
egress: the closed group reaches the gateway alone, and the open group
adds the open egress a session's policy chose; neither admits anything
in. A new machine boots the pool's image, named by its AMI id, the
module's `image_id`; the template maps that image's own root device, so
the root disk itself is encrypted under the pool's key. Its seed is its
first-boot data, which the image reads at each boot, and its metadata
endpoint is closed once its host has traded the key. A snapshot is an
image of the stopped instance under the pool's disk key, held to a
digest of the ids that name its bytes, and read back through the block
API for the scan. `run` and `channel` refuse. Lima stays the local
backend, its image a stopped machine's name, and its seed written
through the hypervisor's channel.

**A machine starts from the session's snapshot, a warm machine, or the
image.** A prepare finds the machine that serves the session, or a
restore replaces it with one started from the session's latest snapshot,
held to its recorded digest first; else it claims a warm one, else it
starts one from the pool's image. It waits a while for the host to enroll
and to prepare the workspace, then the loop waits on the resource. A
spec the machines cannot hold is refused for good: an allowlist, which
needs an egress proxy no machine runs; no egress, where the backend
cannot close it; a limit it does not enforce; and a base.

**A snapshot is the machine's whole disk.** At the end of a run of a
session kept by snapshots, what the workspace holds is pushed while the
host still runs; then the host's credential is ended, the machine
stopped, and its disk kept under the tenant's and the session's names.
The record names the snapshot and its digest, never the disk, and the
step names the digest's hash keyed by the session. The run's release
lets the stopped machine go. The session's purge, its key's revocation,
and its tenant's purge take the disks by those names, in a process whose
machines settings are the runner's. A revocation is a person's call to
the API, whose process reaches no machine: the pool records the erasure
it owes first, and the sweep destroys the disks; a process that reaches
the machines destroys them at once.

**Every path that starts a machine has the one that lets it go.** A
cache session's machine stays warm through the grace, then the runner's
sweep lets it go, its disk with it. The pool's own sweep reads every
machine, a page at a time. It lets go of a first start that died with
its process, one whose session or tenant is gone, and one under the
pool's names that no row holds; then it starts warm machines until the
pool's warm count (`ACME_CLOUD_POOL_WARM`) stands. A new session claims a
started warm machine, and the pool starts another in its place.

**A machine that ran keeps its disk while its session lives.** The disk
may hold work no snapshot has kept yet, so no timer destroys it. A
machine started again keeps its row and its disk, under a new key, and
its host enrolls within the boot bound and the wait after it, counted
from that start, as a claimed warm machine's counts from its claim. A
machine that runs with no host to work for, one that never enrolled in
that time, was ended, or has not called within the silence bound, is
stopped by the sweep, its credential ended first: it bills no compute,
and its session's next prepare starts it again on its disk under a new
key, its host program with it. No person revokes such a host: it ends
with its machine.

## Consequences

- One migration: the pool's machines, the erasures it owes, a pool's and
  a host's session, and a snapshot kept by the machines.
- A session kept by snapshots holds no machine between loops: its next
  loop waits for one to start from its disk, seconds on Lima, about a
  minute in the cloud.
- A machine's host credential sits in its memory, where the session's
  commands, which hold the machine whole, can read it. It claims that
  session's work alone, and ends when the machine stops.
- The open group reaches the platform's network too: the platform's
  insides admit only their own groups, and a machine is in none.
- A warm machine reads its metadata endpoint until a session claims it,
  and runs nothing of a session's until then.
- No deployment runs a machine yet: the runner keeps
  `ACME_WORKSPACE_BACKEND=none` and the pool's image unset. The trigger
  is the platform's cloud account: the environment then calls the
  module, gives the runner and the sweep `ACME_MACHINES_BACKEND=ec2` and
  its outputs, and their task roles its policy.
- A session of the pool whose agent project names a workspace base is
  refused for good. The trigger is a cloud agent project with a
  workspace base: the pool then builds the base on a machine and keeps
  its disk under the tenant.
- A machine's host holds no tenant's secret, so a cloud session's
  environment secret is missing there. The trigger is a cloud agent
  project that declares one.
- A machine of a session kept by snapshots whose run died before its end
  keeps running until a run's end snapshots it, or the session is purged.
- A machine the sweep stopped keeps its disk until its session's next
  loop or its end, as a snapshot would be kept.
- An erasure asked in the API waits for the sweep's next pass.
- A session's pool of one stays with its tenant until the tenant's purge.
- A machine's size is the pool's: a spec that asks for more is refused,
  never met with less.
