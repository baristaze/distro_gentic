# ADR 2076: A small exec payload rides in its item or its result, and a claim carries its item's detail

**Status**: accepted (2026-11-24)

## Context

Every file and output an `exec` item moved crossed the store as an
object
([ADR 2066](2066-a-file-or-an-output-past-its-bound-crosses-the-store-by-a-url-signed-for-it-alone.md)).
That cost each item five calls to the store and one more to the
platform, whatever it printed: an upload started as it was sent, its
parts signed for its host, the host's upload, its completion with the
result, and the runner's read. Most of what a tool call prints is a few
KiB, and those calls carry nothing a sealed field of the item's row
cannot. A host also read each item's detail in a call of its own, right
after the claim that handed it the item.

## Decision

**A file or an output of at most 64 KiB rides inline.** The bound is
`INLINE_BYTES` (`om/exec_relay/types/exec.py`). A write's file rides in
the item's sealed contents. An output, or a read's file, rides in the
result its host pushes. Past the bound, each is an object, as ADR 2066
has it. An item has an output or a read's file, never both, so a result
carries one payload at most, and `RESULT_CHARS` holds it: a result stays
under 180 KiB, and its route is still a holder's call.

**Sealed under the session's key, with the rest of the item.** Inline
bytes are the session's content, as the operation is, and are sealed
with it under the session's key: revoking the key leaves them noise, as
it leaves an object's key. They take no key of their own. An object's
own key keeps the store and the host each to one object; inline bytes
are in no store, and reach only the host that holds their item.

**Held to their size and their digest before anything reads them.** A
host declares the size and the digest of inline bytes as it does of an
object. A result whose inline bytes pass the bound, or miss either, is
refused whole, as one whose hash does not verify is: the bytes came in
the request that declared them, so no store lost a part of them. A host
holds a write's inline file to its size and its digest before a byte of
it reaches the workspace.

**An upload starts when its host first asks to send one.** The send
starts none, so an item whose bytes ride inline makes no call to the
store. The first ask starts the upload and keeps it in the item's sealed
contents. A renewal of the same claim that lands meanwhile moves the
item and settles nothing, and the other lands on the version it left. A
claim after the first lets go of the last claim's uploads, and its host
starts its own.

**Each side says what it reads.** A write's file rides inline only to a
host that reads `exec` work at version 4 (`INLINE_VERSION`). The wire
moves to 4 and its floor stays, so a host of an earlier release is
handed its writes from the store. An output, or a read's file, is read
by the runner that sent its item, so that runner decides whether it
rides inline, not the replica that answers its host: the item records,
as its runner sends it, that this runner reads a result's bytes inline
(`reads_inline`). The detail names the bytes its host may send there
(`inline`), as it says whether the platform keeps a host's times, and
names none for an item a runner of an earlier release sent. A host
sends nothing inline past it, not even an empty file, and a result that
does is refused, so a runner or a platform of an earlier release is
sent objects alone.

**A roll runs both ways.** The API's replicas and the session runners
roll apart, so either may be the earlier release. When the runner is,
its items record no `reads_inline`, their hosts send objects whichever
replica answers, and it reads each result as it always has. When the
API is, an earlier replica names no `inline`, and its host sends
objects; a push may also reach a replica of an earlier release than the
one that answered the detail, which refuses it, and the host pushes it
once more as that release takes it: without its times, and with what
rode inline sent to the store. A rollback runs the same two ways.

**A claim carries its item's detail.** The gateway's claim answers what
a work kind hands its host beyond the payload, from a hook the hosts
service is given by kind (`details`), so no other kind's claim changes.
An `exec` item's is its detail, as its own route answers it, so one call
claims the item and reads it. The route stays for a host that calls it,
and a claim whose detail cannot be read now answers without it.

**A short command sends its output once.** A command whose output rides
in its result, and which ends before its first window of output is sent,
pushes no part of it: the result carries it whole.

## Consequences

- A command that prints within the bound costs the platform two calls,
  its claim and its result, and the store none.
- A runner that streams a short command's output sees it in the result,
  never as a part. A person's terminal shows the result's output when
  no part came.
- Inline bytes sit in the item's row while the item does, sealed, and go
  with it at the session's purge, as an output object does.
- A replica or a runner of an earlier release cannot read an item a
  runner of this one sent: its contents name an upload not started yet,
  or a write's file inline, and its result may carry bytes inline.
  During a roll, such an item fails on that replica and settles by its
  lease. After a rollback, a runner of the earlier release that meets
  one, as a resumed run does, fails that call.
