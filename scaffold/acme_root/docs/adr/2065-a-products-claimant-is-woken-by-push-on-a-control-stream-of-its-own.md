# ADR 2065: A product's claimant is woken by push, on a control stream of its own

**Status**: accepted (2026-10-22)

## Context

A host holds one control stream open, from inside its wall, with its own
credential
([ADR 2004](2004-a-tool-call-crosses-the-wall-as-keyed-exec-work-and-runs-once.md)):
work on its lanes wakes it to claim, and a stop of an item it holds
reaches it as it is made. A product's claimant has no such stream
([ADR 2029](2029-a-products-claimant-enrolls-and-claims-the-way-a-host-does.md),
[ADR 2046](2046-a-claimant-runs-on-the-platforms-claimant-kit-and-installs-through-one-installer.md)).
It learns everything by asking. It gets a job within its wait between
turns, so a product sets that wait short and claims many times a minute
for as long as it runs. It reads the streams its kind reads
([ADR 2038](2038-a-products-claimant-reads-the-streams-its-kind-reads-for-the-item-it-holds.md))
on a timer of its own. It hears that the platform took an item back only
at its next renewal, and its work runs on until then.

## Decision

**A product's claimant holds a control stream, as a host does.** It
opens `GET /v1/claimants/me/control` with its own credential, from
inside its wall. One JSON line a message:

- `wake`: work of a kind it takes reached one of its lanes, in its own
  tenant: claim now. One comes as the stream opens, so a wake missed
  while no stream was open is not lost.
- `revoke`, with the item: an item it held is no longer held under the
  claim it had, whatever took it, its own report included. What still
  works on it stops, and what it sends for it is refused.
- `appended`, with the item and the stream's kind: a stream its kind
  reads gained entries for an item it holds. The work reads it now.
- `ping`: nothing happened.

It carries none of the exec relay's messages. A host's credential opens
no claimant's stream, and a claimant's opens no host's.

**The queue is the record, and the stream reads it again.** The stream
reads what the claimant holds, its items claimed on its lanes and each
claim's token, at least every 5 s, half a second after it said a wake,
so the claim the wake prompts has landed, and once an append names an
item it has not read as held. However many wakes come, it reads at most
once a second. An item it held and holds no more, or holds under another
token, is revoked. The items the claimant names as it opens, those it
works on, are checked at the first read, so a stop made while no stream
was open still reaches it. A work wake, and an append to an item it has
read as held, are said at once.

**A wake is a hint from the bus.** Work landing on a lane is announced
already (`Topics.WORK_AVAILABLE`). An append to a stream of a kind a
claimant reads is announced too, once it is held
(`Topics.STREAM_APPENDED`, with the kind, the item, and its tenant).
Either may be lost: the stream's own read, and the claimant's own slow
turn, catch what a lost wake leaves.

**Only its own reaches it.** A wake is said for its tenant's work of a
kind it takes on a lane its identity names, and an append for its
tenant's item that it holds, of a kind its kind reads. A revoke names
only an item it held. An item it names that is not its own is answered
as revoked, as any item it does not hold is the same `404` elsewhere.

**It ends as a host's does.** After a minute less a jitter, when the
credential it opened with expires, or at the first read after the
claimant is revoked. The claimant opens the next with the credential it
holds then. Admission lets it through uncounted, as it does the host's.

**The kit holds it.** `Claimant.listening()` holds the stream open
beside the claimant's turns and opens it again when it ends.
`Claimant.wait` is the wait between turns, cut short by a wake, so the
claimant's own beat is only its slow fallback claim. `revoked(item)` is
set on a revoke. `appended(item, kind, seconds)` waits for an append or
for its fallback read. A failure reported for a revoked item is not
kept, so the item runs again where it is claimed next; a success is
kept, and lands under a later claim, as ADR 2046 keeps it.

## Consequences

- A claimant claims when work lands, stops when its item is taken back,
  and reads when a stream gains entries. Its calls drop from many a
  minute to a stream a minute and the claims its work needs.
- ADR 2029's claimant claims, reads, renews, and reports at
  `/claimants/...` as before, and now holds its control stream there.
  ADR 2046's turn is still how it claims; the stream says when.
- `KindStreamsInterface.append` takes the item's tenant (`org_id`): a
  product's own code that writes a stream its claimant reads passes it.
- The stream reads the queue through one more query of each layer: the
  items a claimant holds claimed on its lanes. It runs on the claim's
  index, by lane and status. No migration.
- The topics gain `stream_appended`. A process one release behind
  ignores it, and its claimants keep their timers.
- A product's program follows the client's README loop: it opens
  `listening()` around its turns and waits with `Claimant.wait`.
