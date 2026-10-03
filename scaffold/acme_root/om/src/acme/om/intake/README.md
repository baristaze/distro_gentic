# Intake

How the world's events reach a session: a comment, a check, a push, a
ticket, a chat message. This is one of the kinds of thing [Acme is made
of](../../../../README.md).

## What it holds

- **Installation**: a system's installation of the platform, by the
  system's own id, connected by one tenant. Every delivery that names it
  belongs to that tenant.
- **Account link**: an account in an outside system, mapped to a user
  of the tenant. Only a mapped user speaks to an agent as a principal
  from outside.
- **Work binding**: a pull request or a branch that is a session's
  work, so an event that names it finds the session.
- **Platform act**: an act a session made through the platform's one
  account, such as a comment or a push, by the outside system's name
  for what it made. An event that is or follows from that act names the
  session it came from, wherever it lands.

## What can happen

- **Route an event.** An event finds its session by the session id, the
  pull request, or the branch it names, in that order. The routing table
  gives it one effect there:

  | Arrival | Effect |
  |---|---|
  | A principal's message | Wakes; unarchives an archived session |
  | A comment by a mapped user who may instruct the session | Wakes, as that principal's message |
  | Any other person's comment | Wakes, as data |
  | A ticket reopened or reassigned to the agent | Wakes |
  | A bot's comment, a line of CI output | Waits in the inbox |
  | A failing check | Wakes |
  | A passing check | Waits |
  | A person's push to the agent's branch | Hands the session over |
  | Anything for an archived session | Recorded only |

  The session's own acts, which come back as the platform's account, are
  audited and never delivered. Every event is audited once, with its
  effect.
- **Connect** an installation. A person who manages the tenant's members
  hands over the grant the system gave them when they installed the
  platform there. The integration checks it and names the installation.
- **Arrive.** An integration delivers to `/webhooks/integrations/<name>`.
  The integration checks the signature and reads the event. The tenant
  that connected the installation it names is found, and the event is
  queued for that tenant under a key over the integration and its id for
  the delivery, named with what served it, the system or its twin. That is the
  integration's word, never the delivery's, and every record of the
  event names it: the audit entry of its routing, and the first line the
  agent reads.
- **Approve from chat.** A person's yes or no to a call, clicked in chat,
  is decided as the user the chat account maps to.
- **Link an account**, **unlink** one, **bind work** to a session, and
  **record an act** a session makes through the platform's account. A
  person's linked accounts are the channels
  [notifications](../notifications/README.md) reach them on.

## The rules

- **An installation is one tenant's.** It is connected with the system's
  grant, never an id a person types, and no second tenant connects it. A
  delivery whose installation no tenant connected reaches no tenant, and
  nothing a delivery says names one
  ([ADR 2020](../../../../../docs/adr/2020-an-installation-maps-to-one-tenant.md)).
- **Only a mapped user who may instruct speaks as a principal.** Any
  other text from outside is an event: the agent reads it quoted, as
  data, labelled with the origin the platform set, never one the event
  claims.
- **Noise never wakes the agent.** A bot, CI output, and a passing check
  wait for the next model call.
- **The agent never fights a person.** A person's push parks its loop on
  a hand-over that only the person's giving back clears.
- **A chat approval counts only from a mapped user whose role may
  decide the call,** and it is decided and audited as that user.
- **An account is linked by a person, in person,** never by an agent's
  call, and unlinked in person by its user or by a person who manages
  the tenant's members.
- **Every row belongs to one org,** and goes with the org.

<!-- agents-only
The table is `rules.effect_of`. A principal's message is appended under
the mapped user's live context (`PrincipalContext`, the engine's
transition), so `steps` keeps its principal and asks `InstructCheck`;
any other input is a `StepType.EVENT` with `Actor.EXTERNAL` and
`Origin.INTEGRATION`, under a service principal. A hand-over is
`LoopManagerInterface.take_over` under the router's own context. A chat
approval is `ToolsManagerInterface.decide_call` under the mapped user's
context, then an audit entry of that context.
-->

## How another namespace composes it

The delivery consumer hands each event to the router under the tenant's
service context, then hands what the router answered to
[automations](../automations/README.md). An agent's tool that opens a
pull request or pushes a branch binds it to its session.
