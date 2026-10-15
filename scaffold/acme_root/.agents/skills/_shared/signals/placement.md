# Signals: placement

Where each session's work runs, and the platform's read of its fleet
once a sweep pass, across every tenant: the sessions parked, the loops
ready for a runner, and the workspace hosts.

## Gauges

- `acme_sessions_parked`: the parked sessions, by park reason and by
  how long ago each last changed. Many parked on one reason, and old,
  is a fault of that reason's to read: a provider, a budget, a host.
- `acme_loops_ready`: the loops ready for a runner, by the plan tier
  of their lane; every tenant's own lane is one. A tier that only
  grows has too few runners claiming it.
- `acme_hosts`: the workspace hosts not revoked, by state. A host that
  stops beating leaves its sessions waiting on a workspace.
