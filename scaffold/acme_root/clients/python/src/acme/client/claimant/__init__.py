"""The claimant kit: what every client that claims work through the
gateway from inside a customer's wall runs on, whatever its kind. The
workspace host is one; a product's claimant is another (ADR 2046).

- `credential.py`: the claimant's own credential, kept owner-only and
  written whole or not at all.
- `settings.py`: where it finds the platform, its home, its name, and its
  enrollment token, under its environment prefix and its kind.
- `enrollment.py`: enrollment once, the credential picked up at every
  start after, rotated at half its life, and never used once refused.
- `backoff.py`: the wait after a failure it outlasts.
- `journal.py`: the reports not yet sent, kept on its disk first.
- `lease.py`: a lease timed on its own monotonic clock.
- `claimant.py`: a product's claimant on the `/claimants/...` calls:
  claim, renew, and report, with all of the above.

A kind's own calls, such as the host's probes and its exec work, stay in
its own program; the kit holds nothing of one kind."""
