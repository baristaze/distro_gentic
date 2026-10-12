# Connectors

A tenant's own MCP servers, as toolsets its agents load. This is one of
the kinds of thing [Acme is made of](../../../../README.md).

## What it holds

- **Connector**: a tenant's server, by a name that is its toolset's, with
  the line `load_toolset` gives it. A server on the internet has its
  address and names the tenant's secret its calls carry. A server inside
  the tenant's wall is named as the tenant's host runs it.
- **Reviewed tool**: a tool of the server a person bound, at the
  definition they read, pinned by its hash, with the class and the effect
  they gave it and what the [lever checks](../levers/README.md) found in
  its description.
- **Attachment**: a kind the connector is attached to, for one project or
  for the whole tenant, deferred until the agent loads it unless it says
  otherwise.
- **Pin**: what a session holds of its tenant's connectors, written as its
  first run begins.

## What can happen

- **Connect.** A person who manages the tenant connects a server: its
  address, or the name its host runs it by. A cloud server's credential
  is written apart, over the last one, and never read back.
- **List.** What a server on the internet lists now, each tool with its
  hash and its findings, for the person who reviews it. A server inside
  the wall is listed on its host.
- **Review.** A person, in person, binds the tools a session may call, each
  at the hash they read; none withdraws them all.
- **Attach and detach.** The connector joins a kind's sessions, or leaves
  them.
- **Load and call.** A session of an attached kind holds the connector as
  a toolset. Its agent loads it, and calls its tools.

## The rules

- **No tool reaches a model unreviewed.** A session holds only reviewed
  tools, at the definition a person read. A call lists the server again
  and refuses a tool whose definition moved. A tool a person withdraws or
  reviews again stops at its next call in every session.
- **A session's tool definitions never move under it.** It pins its
  connectors once, so a review or an attachment reaches the next session.
- **A connector runs on its session's side of the wall.** One on the
  internet serves the sessions in the platform's cloud, called from
  there. One inside the wall serves the sessions placed there, called by
  the host that holds the session's workspace as `exec` work: the
  platform names it and never opens a connection to it.
- **A credential is never here.** A cloud connector names the tenant's
  secret, resolved at the call and audited by name. A host connector's
  credential stays on its host.
- **The cloud calls the internet alone.** An address that is this host, a
  private network, or a link-local one is refused, as is a name that
  resolves to one, at the connect and at each call.
- **What a server answers is data.** It renders as any tool's output.
- **Every row belongs to one org,** and goes with the org.

<!-- agents-only
The loop asks `root.ConnectorsLayer` (an `AttachedToolsetsInterface`) for
a session's toolsets once a run; a root that runs loops hands it to
`build_managers` as `attached_toolsets`. The pin is `SessionConnectors`,
keyed by the session's id (`storage.create_pin`), and a sub-agent pins
only what its parent pinned (`rules.pinned`). Each tool is the engine's
`McpToolImpl` over an `McpBinding` whose input schema is the server's
(`impl.toolsets.input_model_of`). A cloud call goes through the engine's
`McpServers`; a host call goes through the relay transport's `call_mcp`,
an `exec` item whose request is `relay.types.exec.McpRequest`, which the
host answers from the servers its owner configures (`ceilings.toml`,
`[mcp_servers.<name>]`). Every call first checks the connector's current
review (`rules.still_reviewed`).
-->
