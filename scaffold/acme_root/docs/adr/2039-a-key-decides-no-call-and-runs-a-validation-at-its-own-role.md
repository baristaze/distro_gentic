# ADR 2039: A key decides no call, and runs a validation at its own role

**Status**: accepted (2026-10-05)

## Context

An approval exists so a person sees the exact call before it runs. The
engine records a decision sent on an API key with the program's actor,
and no verdict counts it ([ADR
1017](1017-a-wall-is-checked-at-each-call-and-a-run-reads-what-is-new.md)).
So the key's approval frees nothing, but it is still taken: it lands in
the history as a decision, and the caller is told it was stored.

A validation session is started over the API, often by a CI job on a
key. Its run is platform work on the queue, claimed under the service
role with the starter as the attribution. The session kept no key, so
whatever reads the starter's authority for the run reads the role their
membership holds, above the key's when the key was issued lower.

## Decision

**A key decides no call.** A decision sent on an API key is refused
(`NotAuthorized`, a 403) before anything is read or written, so the
call stays held for a person. This replaces, here, ADR 1017's paragraph
that records it as the program's. The verdict still counts only a
person's decision, so one that reached the history some other way is
none.

**The refusal is of the key, not of every credential but a person's own
session.** A person's approval from chat runs on the live context of the
user the chat account maps to, an internal credential. The platform's
person check (`in_person`) admits only a signed-in session, and would
refuse that approval. So the rule is the one the history already holds:
a decision whose actor would be a program is refused.

**A validation runs on its starter's authority, capped by the key.** The
session keeps the API key it was started on, if one. Its run executes
under its starter's live context, read when it runs: the role their
membership holds now, capped by that key's role, as an agent's
validation runs under its principal's. The executor receives that
context, so one that asks who may run reads the key's role. A starter
who left, a key revoked or expired, or a role that no longer writes
refuses the run for good.

## Consequences

- A program that approved over the API gets a 403. A person approves in
  the portal, the CLI on their own sign-in, or chat.
- A validation session started in person now runs at its starter's live
  role rather than the service role. One whose starter left the tenant
  is refused, where it ran before.
- A session stored before the key column, or written by the previous
  release during a roll, names no key and runs at its starter's own
  role.
- An executor that reads the starter's role from their membership, not
  from the context it is given, still reads the uncapped role. It moves
  to the context's role when its product takes this release.
