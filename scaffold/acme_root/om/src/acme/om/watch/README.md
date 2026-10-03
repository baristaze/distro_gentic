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
- **The stream service's buffers**: the parts the loop emits, a bounded
  buffer per open stream. A stream is the parts of one step. Nothing
  else: the step each adds up to is the record.

It keeps no table. A person's command is the relay's `exec` item, and
the record that it is theirs is an entry in the tenant's event stream.

## What can happen

- **Open a live read.** A viewer who may read the session gets a handle
  that lasts minutes.
- **Read live.** The handle reads the session's open streams, each from
  the part after the last one the reader saw. A late viewer reads the
  buffered tail; a slow one loses the oldest parts, never the newest,
  and is told so.
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
- **A live part is a cache.** Each buffer is bounded, and losing it
  loses nothing the history does not hold.
- **The agent never fights a person.** While it is handed over, the
  agent appends nothing, sends nothing into the workspace, and nothing
  of its own still runs there; nothing of the person's runs once it is
  given back.
- **Every command by hand is recorded as the person's,** before it is
  sent, and runs once.
- **Control is a person's, in person,** and only one who may instruct
  the session takes it.

<!-- agents-only
The service is `impl/stream.StreamServiceMemoryImpl`, the loop's
`StreamSinkInterface`; `StreamOptions` bounds parts and bytes a stream,
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
current epoch, unless `stop`. ADR 2007 records the scoped read.
-->

## How another namespace composes it

A root builds it with `build_watch(managers, stream)`, over the same
stream service the loop emits into. The API issues the handle, serves
the read by the handle alone, and serves take control, a command, and
give back as the person.
