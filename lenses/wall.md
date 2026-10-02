# Wall

Group id: `wall`. Covers Trust and Data, Retention, and the Wall of
`distro_gentic_spec.md`.

This group judges who stands behind each action and what crosses a
customer's wall: the four identities, the agent's lack of authority,
outside text as data, secrets by placement, a tenant's provider keys,
exfiltration, operator access, storage, retention, and the crossing
itself. It leaves a host's own credential and what a host holds to
`placement`, a workspace's stripped environment and its egress to
`workspaces`, a station's limits to `stations`, the routing of a comment
or a chat message to `intake` and `watch`, and the sweep that runs the
retention duty to `fleet`.

## WAL-01 Executor, principal, spender, and actor are four answers

**Principle.** The engine names the actor on every step, the principal
on inputs and tool calls, and the spender on model requests. The
platform adds the executor, a machine's credential, and keeps the four
apart: confusing any two is a defect. An audit entry shows all four, so
"which agent did this, for whom, paid by whom, on which machine" has
four answers.

**Source.** Trust, Four Identities.

**Look for.** The audit entry's fields; every place an executor's
credential is checked, and what it is let stand for.

**Violation.** An audit entry without one of the four; a host's or a
daemon's credential taken as a principal's authority or as a spender;
one field or one credential standing for two of the four.

**Severity.** high

**Check.** review

## WAL-02 The agent holds no authority, and a lapsed principal parks

**Principle.** The agent holds no authority of its own, and the plumbing
runs under the context the guideline's claim builds. So a session whose
creator left the tenant is still recovered, and if its steady principal
is no longer valid, its tool calls park until a person assigns another.

**Source.** Trust, Four Identities.

**Look for.** The context the platform's plumbing runs under; what
becomes of a session whose creator left; what a tool call does when its
steady principal is no longer valid.

**Violation.** A grant or a permission held by an agent; a session that
cannot be recovered after its creator left; a tool call that runs, or
fails the loop, when its steady principal is no longer valid, instead of
parking for a person.

**Severity.** high

**Check.** review

## WAL-03 An approval from chat counts only as a mapped user's

**Principle.** A person's approval from chat counts only when the person
clicking maps to a platform user holding the approve permission, and it
is audited as that user.

**Source.** Trust, Four Identities.

**Look for.** How a chat approval is mapped to a platform user and
checked; what the audit records of it.

**Violation.** An approval that counts from an unmapped chat user, or
from a mapped user without the approve permission; an approval audited
as the chat integration or its bot.

**Severity.** high

**Check.** review

## WAL-04 Text from outside is data, labelled with its origin

**Principle.** Text from outside is data. A comment, an issue, a chat
message relayed by an integration reaches the agent quoted and labelled,
never as an instruction: the engine renders it so, and the platform sets
its origin. A principal speaks only through the portal, the CLI, the
API, an automation, or a mapped user addressing the agent in chat or on
its work.

**Source.** Trust, Untrusted by Default.

**Look for.** Where an integration sets the origin of what it relays;
every path by which text reaches the agent as a principal's.

**Violation.** Relayed text with no origin, or with a principal's
origin; a principal's message by any path but the portal, the CLI, the
API, an automation, or a mapped user addressing the agent.

**Severity.** high

**Check.** review

## WAL-05 A secret is resolved where it is used

**Principle.** An environment secret is declared by name on a project or
a station, with the variable a command sees and a scope. The platform
stores names only. Where it can, the executor brokers the secret outside
the workspace; otherwise the machine that executes the call resolves it
from its own store, short-lived and scoped, injects it into that one
process, redacts it everywhere, and audits its use by name.

**Source.** Trust, Secrets by Placement.

**Look for.** The secret's declaration, and what the platform stores of
it; where a secret is resolved and injected; redaction; the audit of its
use.

**Violation.** A secret's value stored by the platform; a secret
resolved on one machine and sent to another; a secret injected into a
long-lived shell, or into more than the one process; output left
unredacted, or a use not audited by name.

**Severity.** high

**Check.** review

## WAL-06 A cloud secret never crosses a customer's wall

**Principle.** A cloud secret never reaches a customer's host; the
per-session push token is minted for it. A workspace never holds a
platform credential, and a station's secrets and limits never leave its
host. What never crosses into the platform's cloud: a station's limits
and secrets, and the environment secrets scoped to a customer's wall.
What never crosses out to a customer's host: the platform's secrets,
model keys, integration credentials, and the history.

**Source.** Trust, Secrets by Placement; Data, Retention, and the Wall.

**Look for.** Every value the platform sends to a host or a daemon;
every value a host or a daemon sends to the platform; what a workspace
can read.

**Violation.** A platform secret, a model key, an integration's
credential, or the history sent to a host; a station's secret or limit,
or a secret scoped to the wall, sent to the cloud; a platform credential
a workspace can read. (What a host holds is PLC-16.)

**Severity.** high

**Check.** review

## WAL-07 A tenant's key rotates by reference and is never shown

**Principle.** A tenant's own provider key is a secret too. Each
rotation mints a new reference, so a client cached by reference never
serves a rotated key. A key is probed when it is saved. The tenant sees
who added it and when it was last used, never its value. A refused key
parks the sessions that need it.

**Source.** Trust, The Tenant's Provider Keys.

**Look for.** How a key is stored, referenced, and rotated; the probe on
save; what the tenant's view shows; what a refused key does to the
sessions.

**Violation.** A rotation that keeps the old reference; a key saved
without a probe; a view or an API that returns the key's value; a
refused key that fails sessions, or parks sessions that do not use it.

**Severity.** high

**Check.** review

## WAL-08 The rule of two is enforced by policy

**Principle.** The engine's rule of two is enforced by policy, never
hoped for. The platform sets the untrusted mark from the origin of what
a session reads, and the egress allowlist is what makes "beyond its
allowlist" checkable. A session's own branch and its pull request on the
tenant's bound repository are its work product, never an outward write.

**Source.** Trust, Exfiltration.

**Look for.** Where the untrusted mark is set, and from what; how policy
decides an outward write; how the session's own branch and pull request
are classed.

**Violation.** An untrusted mark set by the agent or a prompt, or not
set for content from outside; an outward write judged without the
allowlist; a write beyond the session's branch and pull request on its
bound repository treated as work product.

**Severity.** high

**Check.** review

## WAL-09 Opening a session's content takes a permission of its own

**Principle.** An operator reads a tenant's sessions only through the
operator plane, naming the tenant. Opening a session's content takes an
operator permission of its own, which `read` never implies, so shape is
an operator's to read and content is not, by default.

**Source.** Trust, Operator Access.

**Look for.** The operator plane's reads of sessions; the permission
that opens content, and what grants it.

**Violation.** An operator's read of a session outside the operator
plane, or without naming the tenant; content returned under `read`
alone; a role that grants the content permission along with `read` by
default.

**Severity.** medium

**Check.** review

## WAL-10 Content is sealed per session, under keys a tenant can revoke

**Principle.** Sessions live in `core`; steps, events, and audit are
append-only, in `activity`. Step content is sealed under a key per
session, and the keys live in a key service the tenant can revoke; a
tenant may bring its own key service.

**Source.** Data, Retention, and the Wall.

**Look for.** Where sessions, steps, events, and audit are stored; how
step content is sealed and where its key lives; how a tenant's own key
service plugs in.

**Violation.** A step, an event, or an audit entry updated in place, or
kept in a role other than `activity`; step content stored unsealed, or
sealed under a key shared across sessions; keys the tenant cannot
revoke.

**Severity.** medium

**Check.** review

## WAL-11 Retention is a snapshot that tightening reaches and loosening never

**Principle.** Retention policy is declared per tenant and narrowed per
project: the content's lifetime, the shape's lifetime, the storage mode,
zero retention, and region. A session takes a snapshot of the policy
when it is created. Tightening reaches existing sessions at the next
sweep; loosening never reaches back.

**Source.** Data, Retention, and the Wall.

**Look for.** The retention policy's fields, and where a project narrows
them; the session's snapshot; what a policy change does to existing
sessions.

**Violation.** A project setting that widens its tenant's policy; a
session with no snapshot, or one that reads the live policy; a
tightening existing sessions never get; a loosening applied to existing
sessions.

**Severity.** medium

**Check.** review

## WAL-12 The sweep revokes expired content's keys, and the audit proves it

**Principle.** The sweep revokes the keys of sessions whose content has
expired, and purges shape past its own lifetime. The audit holds each
key destruction as the key service reported it, and a tenant with its
own key service sees the same event in its own logs.

**Source.** Data, Retention, and the Wall; Failure at Fleet Scale.

**Look for.** The sweep's retention duty; what the audit records of each
key destruction, and where that record comes from.

**Violation.** Expired content whose key is not revoked, or shape kept
past its lifetime; a key destruction audited without the key service's
report.

**Severity.** medium

**Check.** review

## WAL-13 What crosses the wall is verified by hash

**Principle.** What is stored where is a decision, never an accident.
Everything that crosses the wall (enrollment, claims, stream parts,
artifacts, results) is opened from inside the wall and verified by hash.

**Source.** Data, Retention, and the Wall.

**Look for.** Each thing that crosses the wall, and where its hash is
checked.

**Violation.** An artifact, a result, or a stream part accepted across
the wall with no hash check. (A crossing opened from outside the wall is
PLC-10.)

**Severity.** medium

**Check.** review
