# The cloud pool

A VM of its own for each session of the platform's cloud whose agent
works in a VM. This is one of the kinds of thing
[Acme is made of](../../../../README.md).

The platform's runner prepares no workspace of its own in the cloud. A
session whose kind asks for a VM runs instead on a VM the pool
starts, through the VMs interface: Lima's on a developer's machine,
an instance of the platform's cloud account in a deployment. The VM
runs the same host program a tenant installs
([hosts](../hosts/README.md)), with Docker inside, so the agent builds and
runs containers of its own. The runner reaches the VM's host through
the [exec relay](../exec_relay/README.md), as it reaches any host: the
host pulls, and the platform never calls in.

## What it holds

- **A VM**: one VM the pool started, under its name in
  the VMs' backend. It names no tenant and no session while it is
  **warm**, started ahead of demand, and names both once a session claims
  it, with the session's **pool of one** and the person its session's
  work is for. A row is written before its VM starts and deleted
  once the VM is gone.
- **A size**: what a session's spec asks its VM by name, `xs`, `s`, or
  `m`, and `s` when it asks none. The deployment's **size map** names
  each size it allows as a machine type, with its CPUs and its memory;
  a warm VM is the default size.
- **A VM key**: a one-use secret the pool hands each VM as it
  starts, in its **seed**, beside where the platform answers. Only its
  digest is kept, until the VM's host trades it for a host's
  credential of the session's pool of one.
- **A session's snapshot**: its workspace's directory, packed in the VM
  and read out through the relay in parts, each sealed under the
  session's key in the snapshots bucket, by the platform's tools
  (ADR 2070). The pool keeps no disk of any VM.
- **An archive record**: the pool's record that a session keeps
  archives, with the latest moment it knew the session active, until
  they go.
- **The pool's limits**: how many VMs stand warm, the most VMs it
  holds at once, and the most one tenant holds, a row per version an
  operator wrote; with none, the pool's options hold.
- **A tenant's own maximum**: the most VMs its sessions hold at once, in
  place of the pool's, which an operator sets or clears.

A VM counts against both maxima from its start or its claim until it is
let go, whether it runs, starts, or stands stopped for its session.

## What can happen

- **Prepare.** A session's loop asks for its workspace. A size the map
  does not name, or an ask of CPUs or memory, is refused for good before
  anything starts. The VM that serves it is found, or a warm one is
  claimed at the default size, or one of its size is started from the
  pool's image. A restore lets go of a VM that serves the session for
  another snapshot, and marks the one it gets for its own, so a prepare
  asked again while it starts keeps it. A claim counts the VMs held under one
  lock. At the pool's maximum, a claim that cannot take a warm VM takes
  the place of an idle one, which goes first. Otherwise, past the pool's
  maximum or its tenant's, it starts none: the loop waits on the
  resource and asks again, its park naming no count.
  The loop also waits while the VM starts and its host enrolls, then
  the VM is sealed and its host prepares the workspace through the exec
  relay.
- **Enroll.** The VM's host trades its key once. While the VM
  is warm it is told to ask again. A cold start records its boot, from
  its start to here, as `acme_cloud_pool_boot_seconds`; a warm claim
  records none.
- **Archive.** At a loop's end, for a session kept by snapshots, what
  the workspace holds is pushed, the pool records the session's
  archives, and the platform's tools keep its directory. The run's
  release lets the VM go, its disk with it, and the next loop's VM
  takes the directory back.
- **Release.** Past the grace, the runner's sweep lets a session's
  running VM go, its disk with it: a cache.
- **Recycle.** At a run's end, once its work is pushed, a VM whose disk
  is a cache and that is past the pool's maximum age goes, and the next
  loop starts another. Nothing lets a VM go for its age under a running
  loop.
- **Sweep.** First the archive records past `archive_kept`, 30 days by
  default: a session active since has its record moved to its last
  activity, and any other loses its archives and their records. Then,
  where the process reaches the VMs, every row is read, a page at a
  time. A first start that died, a VM that ran and is gone, a
  VM whose session or tenant is gone, and one under the pool's names
  that no row holds are let go. A warm VM's row goes first, under the
  claim's lock, so a session that claimed it meanwhile keeps it. A VM
  that runs with no host to work for, its host never enrolled, ended, or
  silent, is stopped, its disk kept: the session's next prepare starts
  it again under a new key. A warm VM past the maximum age goes, its row
  first. Then warm VMs start until the warm count stands, never past
  the pool's maximum.
- **Set the limits.** An operator writes the pool's limits, or a
  tenant's own maximum, and the next claim reads them. Each write leaves
  an audit event naming the operator and the values: the pool's own in
  the platform's stream, which no tenant reads, a tenant's own in that
  tenant's.
- **Purge and erase.** A session's purge takes its VM and its archive
  record, and its archives leave the bucket with its other snapshots;
  its key's revocation takes the record in any process, the API's
  included; its tenant's purge, every VM and record of the tenant.
