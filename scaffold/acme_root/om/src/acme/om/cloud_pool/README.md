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
- **A VM key**: a one-use secret the pool hands each VM as it
  starts, in its **seed**, beside where the platform answers. Only its
  digest is kept, until the VM's host trades it for a host's
  credential of the session's pool of one.
- **A session's snapshot**: the VM's whole disk, kept by the
  VMs' backend under the tenant's and the session's names. The
  platform records its name and its digest in the session's workspace
  snapshots, never the disk.
- **An erasure**: the pool's record that a session's disks are to go,
  until its sweep has destroyed them.
- **The pool's limits**: how many VMs stand warm, the most VMs it
  holds at once, and the most one tenant holds, a row per version an
  operator wrote; with none, the pool's options hold.
- **A tenant's own maximum**: the most VMs its sessions hold at once, in
  place of the pool's, which an operator sets or clears.

A VM counts against both maxima from its start or its claim until it is
let go, whether it runs, starts, or stands stopped for its session.

## What can happen

- **Prepare.** A session's loop asks for its workspace. The VM that
  serves it is found, or a warm one is claimed, or one is started from
  the pool's image; with the session's latest snapshot, one is started
  from that, held to its digest first. A claim counts the VMs held under
  one lock, and past the pool's maximum or its tenant's starts none: the
  loop waits on the resource and asks again, its park naming no count.
  The loop also waits while the VM starts and its host enrolls, then
  the VM is sealed and its host prepares the workspace through the exec
  relay.
- **Enroll.** The VM's host trades its key once. While the VM
  is warm it is told to ask again.
- **Snapshot.** At a loop's end, for a session kept by snapshots, what
  the workspace holds is pushed, the host's credential is ended, the
  VM stops, and its disk is kept. The run's release lets the stopped
  VM go, and the next loop starts another from the disk.
- **Release.** Past the grace, the runner's sweep lets a session's
  running VM go, its disk with it: a cache.
- **Sweep.** Where the process reaches the VMs, every row is read, a
  page at a time. A first start that died, a VM that ran and is gone, a
  VM whose session or tenant is gone, and one under the pool's names
  that no row holds are let go. A warm VM's row goes first, under the
  claim's lock, so a session that claimed it meanwhile keeps it. A VM
  that runs with no host to work for, its host never enrolled, ended, or
  silent, is stopped, its disk kept: the session's next prepare starts
  it again under a new key. The erasures asked are done. Then warm VMs start
  until the warm count stands, never past the pool's maximum.
- **Set the limits.** An operator writes the pool's limits, or a
  tenant's own maximum, and the next claim reads them. Each write leaves
  an audit event naming the operator and the values: the pool's own in
  the platform's stream, which no tenant reads, a tenant's own in that
  tenant's.
- **Purge and erase.** A session's purge takes its VM and every disk
  kept of it; its key's revocation, every disk; its tenant's purge, every
  VM and disk of the tenant. A revocation is recorded first, and
  done at once only where the process reaches the VMs; in the API's
  process, the sweep does it.
