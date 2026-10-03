# Stations

The scarce, located things work needs and cannot carry, the line a
session waits in for one, and the lease a grant gives. This is one of
the kinds of thing [Acme is made of](../../../../README.md).

## What it holds

- **A lab**: the place one station daemon serves, inside a tenant's
  wall. Its stations' work goes to its lane.
- **A station pool**: stations of one kind, with the declared length of
  one holding, which a place's estimate reads.
- **A station**: one of a lab's stations, in a pool, with what it can do
  and how long a lease outlives a job while its session is parked (its
  hold time). Its row is the lease store's: the highest fencing token
  granted on it, and the lease that holds it until when. Its limits are
  not here: they are its owner's, on its host.
- **A daemon credential**: the lab daemon's own, of a kind and a prefix
  (`std_`) no other credential has. The first is issued by an owner or an
  admin and lives a day; the daemon trades it at its start, and every
  one after lives an hour and is rotated at half its life. Only its
  digest is kept. A credential rotates once: rotated again, or presented
  past its grace once rotated, it revokes the lab's daemon. A revocation
  is a mark on each credential, taken under the lab's row lock as every
  rotation is, so no clock reads past it and no rotation lands beside it.
- **A line entry**: one session's ask, for a station or for any of a pool
  with the capabilities it needs, bound to the candidate under test and
  the procedure. Each pool and each station has a line, and a station's
  own line and its pool's are served together, in rank order.
- **A lease**: a time-limited, renewable right to one station, with a
  fencing token one above the station's last. It is a session's, never a
  work item's: an agent session's that waited in line, or a validation
  session's.
- **A job**: what a session sends a station under its lease: operations
  with their parameters, data and never code. Its station, its token,
  and what it runs are the lease's.

## What can happen

- **Make a lab, a pool, a station; issue or revoke a daemon's
  credential.** An owner or an admin.
- **Join a line.** A session asks, and is told its place and an
  estimate. It waits once it is parked on the line, and its park offers
  every station that serves a line it stands in: the sessions every
  namespace is handed carry the offer.
- **Grant.** A free station goes to the first entry in line whose
  session waits. The grant is one conditional write on the station's
  row, and it wakes the session with an event naming the station and its
  lease, and the unlock its park waits for. A session that no longer
  waits is passed, and leaves every line it stood in.
- **Reorder.** A person who manages the stations moves an entry.
- **Leave.** A session leaves every line it stands in.
- **Send a job.** Under a live lease; its station work goes to its lab's
  lane in the same write.
- **Claim, renew, report.** The lab's daemon claims its lab's work,
  renews the lease of the job it runs, as the executor, and reports the
  run. The report lands the run as an execution record, every refused
  command in it, settles the job's claim, and puts the lease back to its
  hold time.
- **Run a validation.** A validation session's station work is claimed
  like any other. It takes a free station of its lab that no session
  waits for, by a lease of its own with no line entry, and its check is
  the job's one command. The daemon's report finishes the session, with
  no agent and no model, and gives the station back to the line. With no
  such station free, it waits on its lab's lane.
- **Release or revoke a lease.** The session lets it go, or a person who
  manages the stations ends it. A revoked lease's session is told, and
  the daemon refuses the lease's next renewal and stops the station.
  Either way the station goes to the next in line.
- **Sweep a lapsed lease.** A lease its session never let go runs out at
  its hold time. The maintenance sweep offers, across tenants, each
  station no live lease holds that a waiting entry asks for, so it goes
  to the first in line who waits. The grant ends the lapsed lease, so a
  second pass grants nothing.
- **Purge.** A tenant deleted past its retention loses all of it.

## The rules

- **One live lease per station.** The grant writes the station's row on
  condition that no live lease holds it: one ended, or past its end by
  more than the margin, does not. A unique index over a station's
  leases that have not ended is the second fence. The token grows with
  every grant.
- **A waiting session is parked on the line.** Only a session parked on
  `rules.LINE_PARK` is granted. One whose loop ended, or that parked on
  anything else, no longer waits: it is never granted, and leaves every
  line. One that has not parked yet keeps its place.
- **A daemon grants itself nothing.** Its identity is its credential's;
  its claims come from its lab's lane alone; it renews only the lease of
  a job it claimed, and only while the lease lives.
- **No limit of a station is here.** No route, view, or job carries one,
  so nothing the platform sends can raise one (ADR 2006).
- **Every row belongs to one org.** A daemon credential's digest is
  unique across orgs, since it is how a daemon's call finds its org.

<!-- agents-only
The daemon's own logic, the fence, the limits, the lease's time on its
monotonic clock, and the report it keeps on its disk until recorded,
lives in `apps/station_daemon` (ADR 2006). The manager methods a daemon
calls take `RequestContext` and a `DaemonIdentity` that only
`authenticate` builds, at the gateway (`gateway/stations.py`); renew and
report run under the tenant's service context, as the person who issued
the lab's first credential, or who sent the job. A session is parked on
the line by its loop; the line reads its status with
`AgentSessionsManagerInterface.project_status`, and the grant's wake is
an event and an `unlock` control through `receive`.
-->

## How another namespace composes it

A session's tool joins a line with `join` and its loop parks on
`rules.LINE_PARK`. The grant's event names the station and the lease; the
tool sends jobs with `submit_job` and lets the lease go with
`release_lease`. The gateway resolves a daemon's credential with
`authenticate`, and calls `claim`, `renew`, and `report`; the run lands
through the evidence namespace's `record_run`.
