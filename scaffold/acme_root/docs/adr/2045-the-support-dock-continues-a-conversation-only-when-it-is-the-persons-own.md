# ADR 2045: The support dock continues a conversation only when it is the person's own

**Status**: accepted (2026-10-05)

## Context

The portal's support dock is a conversation with the platform assistant
beside any page. A person keeps one standing conversation, continued on
each visit, and starts a new one when they choose. The conversation is
an ordinary session of the assistant's kind, so it has an id, a history,
and a page of its own.

The dock needs to find that session again. The API lists the org's
sessions, newest first, by status; it has no filter by kind or by who
started one, and no record of a person's support conversation. Every
member of an org may read the org's sessions, but the dock is a
person's own: no member reads another member's conversation through it.

## Decision

**The browser keeps the id, one per org and person.** When the first
message starts the conversation, the portal keeps its session's id in
local storage under the org's id and the person's (`store/support.ts`).
"New conversation" forgets it, so the next message starts another; the
old one stays a session.

**The dock reads the session back before anything else of it.** It
continues the conversation only when the session is the person's own
(`created_by` is them), of the assistant's kind, and neither archived nor
deleted (`supportModel.ts`). Any other id, whoever kept it, is never read
past the session itself: no step, no stream, no held call. The next
message starts the person's own conversation instead.

**The lists of work leave it out.** A support conversation is a session
of the assistant's kind under the title the dock starts it with,
"Support". No session's title changes after it starts, so the record
says what it is and needs no field of its own (`isSupport` in
`supportModel.ts`). The left bar and All sessions leave such a session
out unless their agent filter names the platform assistant. The dock and
its "As a session" link reach it by its id.

**Each message carries the page as data.** The person's words come
first, then a fenced `page` block of one line of JSON: the address, the
route that serves it, its line from the route catalog, and its
parameters, each clipped. The timeline shows the words alone and the
page they were sent from.

## Consequences

- A second browser, or a cleared one, starts a new conversation. The
  earlier one is still a session the person can open. A record on the
  server would follow the person across browsers; it is worth adding
  when people ask for their support history on a second device.
- The conversation is still one of the org's sessions. It shows under
  the platform assistant's filter, and a member who opens it there reads
  it as they read any session. The dock adds no wall the sessions do not
  have; it keeps a person's own dock to their own conversation.
- A session started from the composer with the platform assistant, whose
  prompt's first line is the one word "Support", is left out with the
  conversations, and shows under the same filter.
- The page block is plain text in the message, so a model reads it as
  the person sent it. It holds only what the address says: a page names
  no secret, and a value a crafted address carries is clipped and stays
  inside its one line.
