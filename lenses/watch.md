# Watch

Group id: `watch`. Covers Watching and Steering of
`distro_gentic_spec.md`.

This group judges how people see and steer a running session: the
realtime channel and the live read, the stream service's buffer,
messages into the inbox, taking control and giving it back, and mirrors.
It leaves stream parts and the inbox themselves to the engine, a host's
control stream to `placement`, the routing of an external event to
`intake`, and the four identities and outside text as data to `wall`.

## WAT-01 The channel carries every change; the live read carries content

**Principle.** The engine streams everything, and the platform carries
it on two paths. The realtime channel carries every change as the
guideline's hint and record: a stream opened or completed, a status
changed, a loop started or ended. The live read carries content, and it
is a read, never a push. This is the platform's recorded deviation from
the guideline's push-first apps, and the channel still carries every
change.

**Source.** Watching and Steering, Live Streams; Deviations from the
Guideline.

**Look for.** What the realtime channel sends; how a viewer gets a
stream's content.

**Violation.** Stream content pushed over the realtime channel; a change
(a stream opened or completed, a status, a loop's start or end) the
channel does not carry; a live read the server pushes.

**Severity.** medium

**Check.** review

## WAT-02 A viewer reads through a short-lived, scoped handle

**Principle.** A viewer is handed a short-lived, scoped handle, the way
a browser app is handed a presigned URL, and reads an open stream from
the part it last saw.

**Source.** Watching and Steering, Live Streams.

**Look for.** How a live-read handle is issued, its lifetime, and its
scope; how a viewer picks a stream up again.

**Violation.** A handle that never expires, or reaches beyond the stream
it was issued for; a read that starts over from the first part, or skips
the parts after the one the viewer last saw.

**Severity.** medium

**Check.** review

## WAT-03 A live part is a cache, and the live view is a window

**Principle.** A live part is a cache whose loss costs nothing, because
the step or artifact it adds up to is the record. The stream service
holds a bounded buffer per open stream, and that is all its state. A
late viewer of an artifact reads its bytes so far; a late viewer of a
model stream sees the buffered tail. A video stream is an index of
encoded segments, and a slow viewer drops the oldest, never the newest.
The live view is a window onto the evidence, never a second world beside
it.

**Source.** Watching and Steering, Live Streams.

**Look for.** What the stream service stores, and for how long; what a
late or a slow viewer gets; whether the live view shows anything the
steps and artifacts do not hold.

**Violation.** An unbounded buffer, or a live part that is the only copy
of what it shows; a slow viewer that drops the newest segments; a fact
shown live that no step or artifact records.

**Severity.** medium

**Check.** review

## WAT-04 Chat instructs only from a mapped user addressing the agent

**Principle.** A message from the portal, the CLI, or a chat surface
reaches the session's inbox over the API, and the engine delivers it at
its next model call. A chat message counts as a principal's only when a
chat user mapped to a platform user addresses it to the agent;
everything else relayed from chat is data.

**Source.** Watching and Steering, Steering.

**Look for.** The path a steering message takes into the inbox; how a
chat relay decides that a message is a principal's.

**Violation.** A message that reaches the session by a path other than
the API and the inbox; a chat message counted as a principal's from an
unmapped user, or one not addressed to the agent.

**Severity.** high

**Check.** review

## WAT-05 Taking control parks the agent and keeps the session as it is

**Principle.** A person who takes control makes the agent stand down,
its loop parked on a hand-over, and the session, its workspace, and its
evidence stay as they are. When the person gives it back, their summary
becomes a message the agent reads on resume.

**Source.** Watching and Steering, Take Control, Give Back.

**Look for.** What taking control does to the loop, the workspace, and
the evidence; what giving it back hands the agent.

**Violation.** Taking control that ends or cancels the loop, releases
the workspace, or resets anything; giving back that resumes the agent
without the person's summary as a message.

**Severity.** medium

**Check.** review

## WAT-06 A person's commands are recorded runs over the same transport

**Principle.** A person's commands run as `exec` work on the host that
holds the workspace, through the same transport and the same stripped
environment, recorded as runs attributed to that person. A remote
desktop would give the person everything and the platform nothing: no
record of what ran, by whom, with what result.

**Source.** Watching and Steering, Take Control, Give Back.

**Look for.** How a person's command reaches the workspace; the
environment it runs in; the run it records, and to whom.

**Violation.** A person's command run over a remote desktop, a direct
shell, or any path outside the transport; a command run with an
environment the agent's commands do not have; a run not recorded, or
attributed to the agent or to the host.

**Severity.** high

**Check.** review

## WAT-07 A mirror subscribes, and a session never waits on it

**Principle.** A session's progress may be mirrored into another
product's agent surface, such as an issue tracker's: thoughts, actions,
questions, and the outcome, coalesced and throttled. A mirror subscribes
to the stream. The session never waits on it and never depends on its
being reachable.

**Source.** Watching and Steering, Mirrors.

**Look for.** How a mirror gets a session's progress; what the session
does when the mirror is slow or down.

**Violation.** A mirror the session calls inline; a loop that blocks,
retries, or fails when the mirror is unreachable; a mirror that posts
every part, neither coalesced nor throttled.

**Severity.** medium

**Check.** review
