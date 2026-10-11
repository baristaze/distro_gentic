# The cloud pool

A machine of its own for each session of the platform's cloud whose agent
works in a VM. This is one of the kinds of thing
[Acme is made of](../../../../README.md).

The platform's runner prepares no workspace of its own in the cloud. A
session whose kind asks for a VM runs instead on a machine the pool
starts, through the machines interface: Lima's on a developer's machine,
an instance of the platform's cloud account in a deployment. The machine
runs the same host program a tenant installs
([hosts](../hosts/README.md)), with Docker inside, so the agent builds and
runs containers of its own. The runner reaches the machine's host through
the [relay](../relay/README.md), as it reaches any host: the host pulls,
and the platform never calls in.

## What it holds

- **A machine**: one virtual machine the pool started, under its name in
  the machines' backend. It names no tenant and no session while it is
  **warm**, started ahead of demand, and names both once a session claims
  it, with the session's **pool of one** and the person its session's
  work is for. A row is written before its machine starts and deleted
  once the machine is gone.
- **A machine key**: a one-use secret the pool hands each machine as it
  starts, in its **seed**, beside where the platform answers. Only its
  digest is kept, until the machine's host trades it for a host's
  credential of the session's pool of one.
- **A session's snapshot**: the machine's whole disk, kept by the
  machines' backend under the tenant's and the session's names. The
  platform records its name and its digest in the session's workspace
  snapshots, never the disk.

## What can happen

- **Prepare.** A session's loop asks for its workspace. The machine that
  serves it is found, or a warm one is claimed, or one is started from
  the pool's image; with the session's latest snapshot, one is started
  from that, held to its digest first. The loop waits on the resource
  while the machine starts and its host enrolls, then the host prepares
  the workspace through the relay.
- **Enroll.** The machine's host trades its key once. While the machine
  is warm it is told to ask again.
- **Snapshot.** At a loop's end, for a session kept by snapshots, what
  the workspace holds is pushed, the host's credential is ended, the
  machine stops, and its disk is kept. The run's release lets the stopped
  machine go, and the next loop starts another from the disk.
- **Release.** Past the grace, the runner's sweep lets a session's
  running machine go, its disk with it: a cache.
- **Sweep.** A start that died, a machine whose host never came, one
  whose session is gone, and one under the pool's names that no row
  holds are let go. Then warm machines start until the warm count stands.
- **Purge and erase.** A session's purge takes its machine and every disk
  kept of it; its key's revocation, every disk; its tenant's purge, every
  machine and disk of the tenant.
