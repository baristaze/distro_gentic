# ADR 2057: A tenant's MCP server is a connector its kinds load, and one inside the wall runs on its host

**Status**: accepted (2026-10-11)

## Context

The engine speaks MCP from the client's side and binds a server's tool
by the hash of the definition someone reviewed ([ADR
1034](1034-an-mcp-client-lists-a-servers-tools-and-each-call-checks-the-pin.md)).
It loads a deferred toolset as a recorded switch ([ADR
1031](1031-a-kind-is-built-from-toolsets-and-a-deferred-toolset-loads-as-a-recorded-switch.md)).
Most tools a role needs outside code come as MCP servers: a tracker, a
wiki, a cloud's read API. They are a tenant's, not the product's. A kind
is the product's, one version shared by every tenant, so a tenant's
server cannot ride on it.

A tenant's server sits in one of two places. One is on the internet,
where the platform's cloud can reach it. The other is inside the
customer's wall, where the platform must never open a connection.

## Decision

**A connector is a tenant's server.** It has a name, which is its
toolset's, and a one-line summary, which `load_toolset` gives it. A
server on the internet has its address, and its credential is the
tenant's secret, kept under a name of the connector's own. The connector
names it and never holds it. The credential is written apart from the
connect, with a PUT, over the last one, and never read back, so the
connect is a create under an Idempotency-Key that carries no secret. A
server inside the wall is named by its host: the platform holds that
name alone. A connector is written in
`core.connectors`. Its reviewed tools and its attachments are its own
lists, read whole.

**A person reviews each tool at the definition they read.** A cloud
server is listed from the platform, and each tool shows its hash and
what the lever checks find in its description ([ADR
2054](2054-a-lever-is-checked-as-a-person-publishes-it-and-read-back-from-the-sessions-that-stalled.md)).
The platform never reaches into the wall, so a host server's review
carries the definitions its host lists. A review names each tool by the
hash the person read, and binds it only at that hash. It gives the tool
its class (`read`, `integration`, or `destructive`) and its effect, said
outright, since a server's own hints are never authority. A call of a
class that acts outward waits for a person, as any outward call does. A
tool takes the name `<connector>__<tool>`, which no tool of the
platform's takes. A review replaces the last one whole, and one with no
tool withdraws them all. Only a person reviews, in person; connecting
and attaching take managing the tenant.

**A connector is attached to a kind, as a toolset.** An attachment
names a kind and a project, or none for every session, and is deferred
unless it says otherwise. A name a kind's toolsets take is refused.

**A session pins its connectors once.** As a session's first run
begins, it pins every reviewed connector attached to its kind for its
project, on its side of the wall, in `core.agent_session_connectors`, keyed by
the session. The pin is written even when it holds nothing. Every later
run reads it, so a review or an attachment reaches the next session, and
a session's tool definitions never move under it. A sub-agent pins only
what its parent pinned, at the same review, so it never holds a tool its
parent does not.

**The loop takes a session's own toolsets.** The engine's loop asks an
`AttachedToolsetsInterface` once a run for what a session holds beyond
its kind. It folds that into the session's kind, so a deferred
connector joins the `load_toolset` line and loads as the kind's own do.
Its tools join the registry beside the catalog's. The session's row
keeps its kind's tools. This is a change to the engine's scaffold: the
next move of the base merges over it.

**Each call checks the review, then the pin.** A call first reads the
connector. A tool no review serves now, at the definition, the class,
and the effect the session holds, is refused. So a person who withdraws
a tool, or reviews it again, stops it at its next call in every
session, and a tool reviewed again as destructive never runs unattended
in a session that pinned it as a read. Then the engine's
client lists the server again, and a moved definition is refused before
the call reaches it. What the server answers is the tool's output: data.

**A cloud server is called from the platform's cloud.** It serves the
sessions in the cloud. Its credential is resolved at the call, audited by
name, and redacted from every answer. Its address is https, and its host
is public: never this host, a private network, or a link-local one. A
name is resolved and held to the same at the connect, at a listing, and
at each call. A name that resolves elsewhere a moment later reads
nothing back: the client never quotes what a server says outside the
protocol. A local stack's servers run beside it, so there this host and
plain http are allowed.

**A server inside the wall runs on the tenant's host.** It serves the
sessions placed inside the wall. Its call is an `exec` item of the
operation `mcp_call` to the host that holds the session's workspace. The
item names the server, the tool, the arguments, and the definition a
person reviewed. The host's owner names each server it starts whole in
`ceilings.toml`: its program, its arguments, its environment, and its
credential, a secret of the host's own store. An item names a server
and nothing it runs, so a compromised control plane cannot widen what a
host starts. The host starts the server for the one call, calls the
tool only when the server lists it as the definition sent, and answers
its text. It names the secret it carried in the item's outcome. The
platform never opens a connection to the server and never holds its
credential. The host imports the engine's MCP client to do this, which
PLC-10's check reads as reaching the platform, so its exception names
this decision.

**A deleted tenant's connectors go with their credentials.** Each
credential leaves the store before the row that names it.

**Not now: a host server listed through `exec` work.** A person brings
a host server's definitions to its review. Trigger: host connectors pass
a tenth of the connectors tenants connect.

**Not now: connectors in the reading of stalled sessions.** The lever
reading names agent playbooks and agent knowledge. Trigger: a
connector's toolset is loaded in a tenth of the sessions that stall.

## Consequences

- A tenant gives its agents a server's tools without a product release.
  A session's cached prefix holds for its life.
- A tool that acts on a server's system waits for a person at each call;
  a read runs unattended where its kind's policy lets it.
- Every session's first run writes one pin row, and every run reads it.
  Every call of a connector's tool reads its connector first, and lists
  the server again.
- A cloud server serves no session inside the wall, and a host server
  none in the cloud.
- A host runs only the servers its owner names. One that names none
  refuses every `mcp_call`, and a host from before this release refuses
  the operation.
- A cloud server's credential is rotated in place: a session's next call
  carries the value written last.
