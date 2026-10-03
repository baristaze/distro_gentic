# The maintenance worker

The background process of Acme. Every replica runs three things side by
side, started in `main.py`.

- **The work loop** (`loop.py`) claims items from the work queue on its
  lane and runs each under the context the claim built. It renews each
  lease, and completes, fails, parks, or refuses the item. The handlers are
  in `handler.py`, `orchestrations.py`, `accounts.py`, `sessions.py`, and
  `validations.py`, which runs a validation session's check on the
  platform's fresh executor.
- **The delivery consumer** (`deliveries.py`) long-polls `Queues.WEBHOOKS`,
  where the API queues each provider's verified delivery, and applies it
  once in the org it names. A message that can never apply is dropped; any
  other failure comes back. An integration's event (`feedback`) is routed
  to the session it names by [intake](../../om/src/acme/om/intake/README.md),
  then fires the tenant's
  [automations](../../om/src/acme/om/automations/README.md).
- **The sweep** (`loop.py`) runs on a timer, within a budget. It requeues
  expired leases, relays the outbox, ticks each tenant once (its
  automations' schedules, each fired once a slot whichever worker ticks
  first), purges every row past its retention (`settings.py`), counts the
  platform's size, and logs the queue's gauges.
  It carries the platform's duties too, each its owner's, across tenants
  (`across` in `main.py`): the keys and shape past their retention, a hold
  nobody settled, settled through its gate, an exec item whose host's lease
  ran out, and a session pending with no loop, whose run it asks for again
  (`sessions.py`;
  [ADR 2015](../../docs/adr/2015-the-fleet-recovers-through-the-sweep.md)).
  A host never runs it: it holds no worker, no manager, and no storage.

`serve` runs the three; `health` asks the running process's `/healthz`.

## Adding a work kind

Add the kind, its payload, and the permission that asks for it in
`acme.om.work`. Write a handler that names the permissions it calls with
(`REQUIRES`), and add it to `handlers` in `build_loop`; a test holds the
two to each other. A long-running kind is an `OrchestrationKind` whose step
is mapped in `build_loop`.

## Adding a delivery provider

Implement `DeliveryProviderInterface`: read the delivery, name its org, and
apply it under an id derived from its key, so a copy changes nothing. Add it
to `providers` in `build_consumer`, under the name the API queues it with.
