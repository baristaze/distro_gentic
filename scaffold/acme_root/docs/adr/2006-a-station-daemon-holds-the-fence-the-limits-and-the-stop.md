# ADR 2006: A station daemon holds the fence, the limits, and the stop

**Status**: accepted (2026-10-02)

## Context

The guideline's DEL-01 keeps apps dumb: a client of the gateway shows
and sends, and the platform decides. A station daemon is such a client.
It sits on a station's host, inside its owner's wall, and pulls its
lab's station work through the gateway, as the CLI and a workspace host
do.

But a station is a scarce, located thing, and what reaches it can do
harm the platform cannot undo. The platform can be slow, gone, or
wrong. A lease the platform thinks has ended may still be running a job
on the host, and a command from an older holder may arrive after a newer
one's. The guard nearest the resource has to hold in every one of these
cases, so it cannot be the platform's.

## Decision

**The daemon holds logic, and this is the deviation from DEL-01.** It
decides four things itself, from what it holds on its own host.

**The fence.** Each grant of a station carries a fencing token one above
the last, and the daemon keeps the highest it has seen for each station,
on its disk. It checks every command against it. A lower token is
refused. A higher one is taken only after the station has taken its
declared controlled stop and its baseline is restored.

**The limits.** A station's limits (a speed, a current, an envelope,
the firmware it accepts) are its owner's, in `stations.toml` on the
host. The daemon reads them at startup and holds them frozen. No route,
view, or job carries one, so nothing the platform sends can raise one. A
command past a limit, or an operation the station does not accept, is
refused, and the refusal ends the job.

**The lease's time.** The platform answers how many seconds a lease has
left, never until when. The daemon times them on its own monotonic
clock, from the moment it asked, so its deadline falls before the
platform's. The platform grants a station again only after a lease's end
plus a margin for clocks and the answer's way back.

**The platform gone.** A daemon that cannot reach the platform lets its
current job run to its lease's end on that clock, then stops the
station, and claims no new job until the platform answers again.

**The platform's side stays small.** One live lease per station is the
lease store's. A grant is one conditional write on the station's row,
which fails while a live lease holds it, with the lease and the line
entry it settles in the same commit. A unique index over a station's
leases that have not ended is the second fence. The daemon's credential
is a kind of its own (`std_`), issued by an owner or an admin for one
lab and rotated by the daemon. Its routes take nothing but the version
of `station` work it reads: its lab, its tenant, and its lane are the
credential's. It renews only the lease of a job it claimed, and grants
itself nothing.

**A refused command is evidence.** The daemon writes the job's report,
every refused command in it, to its disk before it sends it, and keeps
it there until the platform recorded it. The platform records the run as
an execution record, the record every run is: a run a refusal ended is
`aborted`, names the refusal, and lists each refused command.

## Consequences

- The daemon's fence and limits are code on a customer's host. They are
  held by the daemon's own tests, and by the stations lenses at review.
- A job is data, operations with their parameters, run through the
  station's adapter. No code a job holds runs in the daemon, and a
  station's device access is declared, line by line, in the host's
  service configuration the daemon prints.
- A lease revoked while its job runs is stopped at the daemon's next
  renewal, at most half a renewal's length later.
- A daemon cut off from the platform keeps its reports. They are recorded
  when it reaches the platform again, so a run's record can arrive late,
  but it arrives once, under the run id the daemon minted.
- A session waits in a line only once it is parked on it. One that joins
  and has not parked yet keeps its place and is passed over. Wiring the
  loop so a tool's call parks it on the line is the engine's step, not
  this one.
