# Watch

How a person sees and steers a running session. This is one of the
kinds of thing [Acme is made of](../../../../README.md).

A person watches a session think, steers it with a message, and, when
they need their hands on the work, takes control and gives it back. A
message reaches the session's inbox over the API, the way every input
does; a chat message counts as a person's only as
[intake](../intake/README.md) routes it.

## What it holds

- **A live-read handle**: one session's open streams, readable until
  the handle expires. It is signed, the way a presigned URL is, so a
  read needs no session of its own and no database.
- **Stream kinds**: one registry (`kinds.py`) of the kinds of live
  stream, each with the bounds every stream of it is held to. The step's
  parts are the platform's kind; a product registers its own, which it
  writes and reads in groups of their own. A product's kind may name its
  claimant kind, which writes it for the item it holds, in a group per
  item, and the claimant kind that reads it there.
- **The stream service's buffers**: the parts of each open stream, a
  bounded buffer per stream on the shared cache. A stream is the parts of
  one step. Nothing else: the step each adds up to is the record. The
  session runner writes them as its loop streams, and the API reads them,
  so a viewer watches a step from a process other than the one that runs
  it.

It keeps no table. A person's command is the relay's `exec` item, and
the record that it is theirs is an entry in the tenant's event stream.

## What can happen

- **Open a live read.** A viewer who may read the session gets a handle
  that lasts minutes.
- **A claimant appends.** A product's claimant appends to a stream of
  a kind its own kind writes, for the item it holds under a live lease
  and its claim token, at most a bounded batch at a time, each entry
  with the hash it crossed the wall with. Any other item or kind is not
  found, an entry that does not match its hash is refused, and nothing
  lands.
- **A claimant reads.** A product's claimant reads the streams of a
  kind its own kind reads, for the item it holds under a live lease and
  its claim token, from the entry after the last it read. Any other item
  or kind, and a lapsed lease, are not found, and nothing is read.
- **Open an item's read.** A viewer who may read the item's tenant gets
  a handle to the item's streams of one kind, as a session's.
- **Read live.** The handle reads the session's open streams, each from
  the part after the last one the reader saw. A late viewer reads the
  buffered tail; a slow one loses the oldest parts, never the newest,
  and is told so.
- **A stream opens and completes.** Each is an entry in the tenant's
  event stream, under the session, and a hint on the realtime channel.
  A completed stream is gone from the cache: its step is stored.
- **Take control.** The agent stands down: a new writer epoch fences
  the run that held the loop, which parks on a hand-over, and what that
  run still runs on the host is stopped. The session, its workspace,
  and its evidence stay as they are.
- **Run a command.** While the agent stands down, the person's command
  runs as `exec` work on the host that holds the workspace, through the
  [relay](../relay/README.md), in the workspace's own isolation. The
  host reads it as a person's, which its owner may refuse.
- **Give back.** The person's summary becomes their message, and the
  next run continues the loop under an epoch that fences any command of
  theirs no host took yet. A command of theirs still running refuses
  it, unless the person asks it stopped.

## The rules

- **The channel carries every change; the live read carries content.**
  The read is a read, never a push.
- **A handle reads one session, and not for long.** A handle that does
  not verify, or has expired, reads nothing.
- **A handle reads what it was signed for.** A session's handle never
  reads an item's streams, nor an item's a session's.
- **A live part is a cache.** Each buffer is bounded, and losing it
  loses nothing the history does not hold. A kind nobody registered has
  no bound, so nothing streams it.
- **The agent never fights a person.** While it is handed over, the
  agent appends nothing, sends nothing into the workspace, and nothing
  of its own still runs there; nothing of the person's runs once it is
  given back.
- **Every command by hand is recorded as the person's,** before it is
  sent, and runs once.
- **Control is a person's, in person,** and only one who may instruct
  the session takes it.

<!-- agents-only
The service is `impl/stream.StreamServiceImpl` over infra's
`StreamsInterface` (Valkey when the cache is, memory otherwise), built
by `root.build_stream`. It implements the loop's `StreamSinkInterface`:
the session runner passes it to `build_managers` as `stream_sink`, and
the API to `build_watch`. A stream writes at most once a
`StreamOptions.window` (100 ms): the first part after a quiet window
goes at once, and the parts behind it are held, one run of a block's
parts joined into one part that holds the places `n` to `last`, until
the window ends, a new block starts, `completed`, or `join_bytes`. A
reader resumes after a part's `last`, so its mark and its `dropped` stay
exact. An emit, `opened`, or `completed` is queued
(at most `max_queued`, the oldest dropped) and written in order by one
task: parts of a step in one append to the stream `step_id` of the
group `session_id`, each entry numbered by its part's `n`; `opened` and
`completed` as `watch.stream.opened`
and `watch.stream.completed`, appended under the session with the
step's id, then published as `ENTITY_CHANGED`; `completed` ends the
stream first. A read keeps a part only when it names the session and
the step it is read under. `StreamOptions` bounds parts and bytes a stream,
streams a session and overall, and closes a stream idle past `idle`. The
handle is `rules.signed`/`rules.verified` (HMAC-SHA256 over a purpose
prefix and the `Grant`), keyed by `WatchOptions.live_read_key`; none
refuses every live read (`Unavailable`). A command's id is
`relay.rules.exec_id(key, request, 0)`, audited as `watch.command.sent`
under an id derived from it before `RelayManagerInterface.send`, with
the session's cursor epoch read before its park, and sent with
`ExecCall.by_person`, which lands in `ExecPayload.by_person` for the
host's `people_commands` ceiling. Take control and give back are the
engine's `take_over` and `give_back`, audited as `watch.control.taken`
and `watch.control.given_back`. Take control then calls
`relay.interrupt_running` below the new epoch; give back reads
`relay.running` and raises `CommandRunning` for an item under the
current epoch, unless `stop`. ADR 2007 records the scoped read. An
item's handle is `rules.signed`/`rules.verified_item` over an
`ItemGrant`, under its own purpose prefix. `append_as` checks the kind's
writer (`StreamKind.claimant`), the bounds `MAX_APPEND_ENTRIES` and
`MAX_APPEND_BYTES`, each entry's `stream_part` crossing
(`crossing.verified`), then `hosts.held_as` and the lease, and appends
through `KindStreamsInterface` in the item's group. ADR 2030. `read_as`
checks the kind's reader (`StreamKind.reader`), then `hosts.held_as` and
the lease, each refusal the same `NotFound` (a `LeaseLost` from
`held_as` among them), and reads the item's group as `read_item_live`
does. ADR 2038.
-->

## How another namespace composes it

A root builds it with `build_watch(managers, stream, kind_streams=...)`,
over the stream service `build_stream(infra, events)` builds and a
product's kinds' streams `build_kind_streams(infra, kinds)` builds. The session runner hands
the same kind of service to the loop as its sink, so the API's reads
find what the runners stream. The API issues the handle, serves
the read by the handle alone, and serves take control, a command, and
give back as the person.
