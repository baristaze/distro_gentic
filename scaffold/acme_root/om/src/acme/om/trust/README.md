# Trust

Who stands behind each act of an agent, and what crosses a customer's
wall. This is one of the kinds of thing [Acme is made
of](../../../../README.md).

## What it holds

- **Audit entry of a call**: for every tool call an agent makes, four
  answers kept apart. The **executor** is the machine that ran it, by
  its credential. The **principal** is whom it ran under. The
  **spender** paid for the model call that chose it. The **actor** is
  the agent that asked. The last three come from the
  [steps](../steps/README.md) and [attribution](../attribution/README.md);
  the executor is what this namespace adds.
- **Secret declaration**: a secret by name, never by value. It names the
  variable a command sees, the scope the credential is made for, what it
  is declared on (a project or a station), and the store that holds its
  value: the platform's own, in its cloud, or the store of the machine
  that runs the call, inside a customer's wall.
- **Provider key**: a tenant's own key to a model provider, by
  reference. The record says who added it, when, and when it was last
  used. The value sits in the secret store under the reference, and in
  no record.
- **Content grant**: the permission that lets one operator open one
  tenant's session content, until it expires.

## What can happen

- **Audit.** Before a tool call runs, its entry is written into the
  tenant's event stream, once.
- **Take over.** A person takes over a steady session whose principal
  no longer holds its place. The session was waiting for exactly that,
  and wakes; its calls now run under that person. Its sub-agents waiting
  the same way follow, and wake too.
- **Declare a secret, and give a cloud secret its value.** One who
  writes the tenant's configuration does both. A secret held inside a
  customer's wall never takes its value here.
- **Refuse a crossing.** A call whose tool would use a secret on the
  far side of its session's wall is refused before it reaches a
  machine, and the agent reads why, by the secret's name.
- **Save a provider key.** The provider is asked first whether it takes
  the key. A key saved gets a new reference and becomes the live one;
  the key it replaces is marked rotated, and its value leaves the store.
- **Serve a client.** A client built on a key is kept by the key's
  reference, and served with it. The live reference is read on every
  call, so a client built on a rotated key is never served again.
- **Refuse a key.** A key the provider does not authenticate on a call
  is marked refused and its client closed; its value is kept. Every
  session that needs it waits until the tenant saves a new one. A
  permission the key lacks refuses nothing: only the session that met it
  waits.
- **Read as an operator.** An operator with `read` reads a session's
  shape: its steps' places, types, and headers. Opening what it says
  takes a content grant in that tenant, and each opening lands in the
  tenant's own event stream.

## The rules

- **Executor, principal, spender, and actor are four answers.** No
  field stands for two, and a machine's credential stands for no person
  and no key.
- **No authority, no call.** A steady session whose principal left
  waits for a person. A message from someone else does not wake it.
- **A secret is resolved where it is used.** A cloud secret never
  reaches a customer's host. A secret held inside the wall never crosses
  into the cloud. A secret never declared is a cloud secret.
- **A station's secret stays on its host.**
- **A rotated key is never served,** and neither is a refused one.
- **The tenant sees its key, never its value.**
- **`read` never opens content**, and neither does `write`. Only a
  grant the grant job writes does ([ADR
  2010](../../../../../docs/adr/2010-content-opens-by-a-grant-of-its-own.md)).
- **Every row belongs to one org,** and goes with the org: each value in
  the store leaves before the row that names it.

<!-- agents-only
Placement is the hosts' concept: `placement.PlacementInterface` declares
the one fact the secrets read (inside a wall or not) and the one answer
the audit reads (the executor), with `impl/placement.PlacementCloudImpl`
as the default. The trust layer (`root.TrustLayer`) wraps the engine's
tools manager through `build_managers(tools_layer=...)`; the decorator is
`impl/tools.ToolsManagerTrustedImpl`. The audited principal is the one
the call's context speaks for (`attribution.rules.principal_of`), never
the tool request's header, which a take-over leaves behind.
-->

## How another namespace composes it

A root wraps the engine's tools manager in the trust layer, so the loop
reaches every call through it, and builds the trust managers over the
engine's. The hosts answer where a session runs and on which machine;
until they do, every session runs in the cloud.
