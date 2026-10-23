# ADR 2066: Every file and output an exec item moves crosses the store by a URL signed for it alone

**Status**: accepted (2026-10-23)

## Context

A tool call into a tenant's wall travels as keyed `exec` work, and the
session's content it carries is sealed under the session's key
([ADR 2004](2004-a-tool-call-crosses-the-wall-as-keyed-exec-work-and-runs-once.md)).
A file's bytes inside an item, and what a command printed inside its
result, would ride base64 in JSON, held whole in the API's memory and in
the host's, each size with a bound of its own. A repository bundle
reaches 512 MiB. The call that settles an item is a holder's call
([ADR 0106](0106-a-holders-calls-are-counted-apart-from-its-writes.md)),
which must stay small whatever the command printed.
Every blob between a client and a bucket goes by a presigned URL,
whatever its size, and every upload is multipart
([ADR 0107](0107-a-blob-crosses-by-a-presigned-url-and-every-upload-is-multipart.md)).

## Decision

**A file or an output is an object, never a field.** An item names an
object in the store's `tool-outputs` bucket, under its tenant, at
`exec_relay/<session>/<item>/<dispatch>/<kind>`, for each thing it moves:
the file a write hands its host, the file a read's host uploads, and
what a command, a call of a server's tool, or a listing printed, its
`output`. The item carries each object's reference, and of a file it
hands, its size and its digest. A result names each object its host
uploaded by its size and its digest. Nothing else of the bytes is in an
item, a result, or any request to the API.

**Each object is sealed under a key of its own.** It is a run of 1 MiB
frames, each AES-256-GCM with a nonce of its own, bound to the object's
reference, its place, and whether it is the last
(`acme.infra.buckets.sealed`), so the parts of the store's plan hold
whole frames. The key is kept in the item's sealed contents, under the
session's key, as the operation is. Revoking the session's key leaves
those contents unreadable, and with them every key that opens one of the
item's objects: the objects are noise.

**What a host is handed, what it reads, and for how long.** The detail
of an item, which only the host that holds it reads, hands it:

- for a write, the file's reference, size, digest, and key, and a URL
  signed for a GET of that object alone, good for 15 minutes
  (`ExecRelayOptions.object_ttl`) to start reading;
- for an object it uploads, its reference and its key. It asks
  `POST /v1/hosts/me/exec/{id}/upload` with the size it seals, and is
  answered the parts the store does not hold, each by a URL signed for
  its number and its length, good for 15 minutes. Asked again, it is
  answered only the parts still missing, so an upload cut off resumes.

The key opens that object and no other, and each URL reads or writes it
alone: the store refuses a URL whose path was changed, and one past its
time. Another host is handed neither. The host keeps no key past the
item.

**A host moves an object off the loop that holds its leases.** Each
transfer runs on a store connection of its own, does its sealing, its
hashing, and its disk in a thread, and spools on the host's disk. A
download is opened frame by frame and hashed as it arrives, and nothing
of it reaches the workspace until its size and its digest match; the
host's transport then writes it from disk (`WritesFromFileInterface`). A
read is spooled from the workspace a chunk at a time, and sealed a frame
at a time as each part is sent. The lease is renewed until the result is
pushed, the transfers included.

**A result is a few KiB.** It holds the outcome, why its host refused
the item (1,000 characters at most), the offset a read echoes, and each
object's size and digest; `RESULT_CHARS` is derived from them. A relayed
command keeps at most 1,000,000 characters of each stream, the engine's
default, and the host sends its result as UTF-8 JSON. The route that
takes the result and the one that signs an upload's parts are holder's
calls, and neither carries bytes.

**The platform reads only what matches.** A result completes the upload
of each object it names before it lands, so whoever reads the item done
finds its objects whole. An output that is not whole is not kept, and
the result says so; a read whose file is not is refused. The runner
reads an output, or takes a read's file, from the store and opens it
against the size and the digest its host declared; one that does not
match is refused. The platform's own write, a write's file, is a `put`,
as ADR 0107 has a service write.

**An object lives as long as what it carries.** A write's file leaves
the store once its item settles. A read's file leaves once the runner
takes it, or once its item settles without one. An upload a result names
nothing of is aborted. An item's output is its record, so it stays while
the item's output stays, until the session's purge, which removes every
object its items moved. A claim after the first starts each upload over,
so a host sends only what its own claim sealed; an item sent again moves
objects of its new dispatch, and the last one's go. A version the bucket
keeps of a removed object is sealed under a key that goes with its item.

**The exec wire moves to version 2.** A host of an earlier release reads
a file and an output inside the item, so the floor rises with it: such a
host is handed no work until it is upgraded.

**A product's claimant moves a file the same way.** The calls are the
client's (`Transport.store()` and the URLs the platform signs), and the
sealed format is infra's. The claimant kit gains nothing now: no
claimant's kind moves a file yet, and one that does takes these, never a
second path.

## Consequences

- One path carries every size. A relayed read reads what its caller
  asks, so a bundle within the repository's 512 MiB bound crosses, and a
  host's memory holds a few frames of a file of any size.
- An item that moves bytes costs the store a few calls: an upload
  started as it is sent, its parts signed, its completion, a read, and a
  removal. A command's output goes this way however small it is, as ADR
  0107 has no shortcut for a small file.
- The runner still holds a write's file and a read's file whole, since
  the engine's transport hands and takes bytes.
- The engine's transport types gain `WritesFromFileInterface`, which the
  local, container, and twin transports implement, so the next move of
  the base merges over it. The client's `Transport` gains `store()`,
  which the media calls use too.
- An object the store fails to remove is left, sealed, to the session's
  purge; an upload left open is ended by the bucket's own rule a day on.
