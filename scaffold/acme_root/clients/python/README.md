# Acme Python client

The one Python client of the Acme API. Every Python consumer goes through
it, and nothing else in Python calls `/v1/*`.

- `schema/` is generated from the committed documents,
  `clients/openapi/`, by `make openapi`: one module per namespace, which
  imports another's module where it uses its types. Never edit it by
  hand.
- `types/` is the facade consumers import: one module per namespace, the
  views and enums by name (`acme.client.types.tenancy`).
- `transport.py` is the one transport. Every call carries the bearer, the
  app headers, and a timeout. A creating call carries an idempotency key.
  A failure that can differ is retried with jittered backoff. A refusal is
  an `ApiError` with its code and request id. TLS uses the system trust
  store.
- `calls/` holds each namespace's operations, one module per namespace,
  and `client.py` composes them onto the transport as `ApiClient`.
- `envelopes.py`, `stream.py`, and `realtime.py` are the socket's frames,
  the placement rule, and the channel, which yields every change once, in
  stream order.
- `claimant/` is the claimant kit: what a client that claims work through
  the gateway from inside a customer's wall runs on, whatever its kind.
  It enrolls once, keeps its credential owner-only and writes it whole or
  not at all, rotates it at half its life, while a work runs too, never
  sends it once refused, waits out a failure, and keeps each report in a
  journal until the platform records it. The workspace host runs on it;
  a product's claimant does too, through `Claimant` and the
  `/claimants/...` calls, with its control stream held open beside its
  turns, so it is woken to claim, to stop, and to read, and its own
  timer is only the fallback.

```python
async with ApiClient(url, app="cli", app_version="cli@0.1.0", token=token) as api:
    stored = await api.upload(await api.start_upload("spec.pdf", "application/pdf", size), data)
    async for change in Channel(api):
        print(change.kind, change.target_id, change.actor_id)
```

```python
claimant = Claimant(ClaimantSettings.from_env("ACME", "scanner"), client_for)
await claimant.start()  # enrolls once, or picks up its credential
async with claimant.listening():  # the control stream, open beside the turns
    while True:
        turn = await claimant.turn()  # rotates, sends the journal, claims
        if turn.item is not None:
            async with claimant.keeping_alive():  # rotates every beat while it works
                outcome = await work(turn.item, claimant)
            await claimant.report(turn.item, outcome)
        await claimant.wait(turn.wait)  # a wake on the stream cuts it short
```

Inside the loop, a work opens `claimant.client()` for each call or short
burst and never holds one across a beat, since a rotation retires the
token a held client carries a minute later. It stops once
`claimant.revoked(item)` is set: the platform took the item back. A work
that reads a stream its kind reads waits on
`claimant.appended(item, kind, seconds)` between reads, and the seconds
are its slow fallback read.

```bash
uv run pytest -q clients/python/tests
```
