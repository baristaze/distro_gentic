# Integrations

The third-party providers Acme talks to: the identity provider, the
model providers, and the integrations whose events reach a session. Each is one interface with a real client and a twin,
and a caller never knows which it holds. Nothing here imports the object
model: a provider's errors root at infra's exception family, since a
provider is a dependency the way a backend is.

## The identity provider

`identity.IdentityProviderInterface` proves who a person is and holds
an org's side of it:

- the hosted sign-in, the code exchange, the device sign-in for the
  command line, and the logout address that ends the provider's session
  in the browser;
- an org's organization at the provider, its single sign-on link, and
  its invitations;
- the deletion of a deleted account's user and a deleted team org's
  organization;
- the check of an inbound delivery (`verify_delivery`).

The provider hands Acme an issuer, a subject, and a verified email.
Everything else (the identity row, its sessions, its memberships) is
Acme's own; [the tenancy namespace](../om/src/acme/om/tenancy/README.md)
says how a sign-in becomes a person.

| Implementation | What it is |
|----------------|------------|
| `identity/workos.py` | WorkOS AuthKit through the pinned `workos` SDK. At start it proves the key is the application's, and refuses to boot on any other ([ADR 0033](../docs/adr/0033-the-workos-key-is-the-applications.md)). |
| `identity/twin.py` | The provider in memory, for tests and CI. It signs its own deliveries with the provider's scheme. Every id it mints starts with `twin_`. |
| `identity/absent.py` | The provider of a process with none configured, a local stack with no key among them: every call is `ProviderUnavailable`, which the API answers as `503`. The local sign-in by address still works. |

## The webhook check

The provider delivers its events to `POST /webhooks/identity`. The
route takes no credential; the signature is the authentication.
`identity/deliveries.py` checks the `WorkOS-Signature` header, an
HMAC-SHA256 over `<timestamp>.<body>` under `ACME_WORKOS_WEBHOOK_SECRET`,
inside a three-minute window, in constant time. A delivery that fails
is `400 webhook_signature_invalid`, and nothing is queued. One that
passes is queued on `webhooks` with a key that is a UUID v5 over the
provider's event id, so a redelivery carries the same key. The
maintenance worker applies it.

## The integrations

`events.IntegrationInterface` is an integration whose events reach a
session and through which a person is told what waits on them: the forge
that holds a session's work, and the chat its people talk in
(`events.INTEGRATIONS`). Each delivers to `POST
/webhooks/integrations/<name>`. The integration checks the signature
over the body and its timestamp, reads the event into the platform's
terms, and keys it with a UUID v5 over its name and its id for the
delivery. The installation a delivery came through is the system's own
id; the tenant that connected it is the one the event is queued for. An
integration also confirms the grant its system hands the person who
installs the platform there (`verify_installation`), by the system's
signature or by a call to the system, so a tenant connects the
installation the system names, never one a person types. It also
posts a message to an account of its system. The forge also points a
session's branch or snapshot at a commit (`push`), taking the commits it
needs as a git bundle the platform made, and opens its pull request
(`open_pull_request`), with the integration's own credential, which never
leaves it. A ref only moves forward, and a move that does not is refused
with a message that says so; only the one named is written;
a second opening of one branch answers the pull request it opened.

What served an event is the integration's word (`provenance`), never the
delivery's, so a twin's event is a twin's whatever its body claims. A
delivery that checks out and is the system's check of the address it
delivers to, a ping or a challenge, is `Acknowledged`: the ingress answers
it with what the system asks back and queues nothing. Any other delivery
that is no event the router reads is refused.

| Implementation | What it is |
|----------------|------------|
| `events/twin.py` | The twin of every integration, in memory. It signs its own deliveries (`Twin-Signature`, HMAC-SHA256 over `<timestamp>.<body>`, a five-minute window) and its installations' grants the same way, records each message posted through it and each ref and pull request it took, has one installation per repository owner (`twin_installation_<owner>`), which holds that owner's repositories, and refuses a forge write through any other, and, made to write (`writes`, as the local stack's forge twin is), pushes each ref's commits to the repository for real (`events/git.py`), with a repository's credential where it is given one, says `twin` on every record it writes, and mints every id as `twin_`. Refused at boot outside `local` and `test`. |
| `events/github.py` | The forge as a GitHub App ([ADR 2027](../docs/adr/2027-the-forge-is-a-github-app-and-the-chat-a-slack-app.md)). It signs a JWT with the App's private key and trades it for each installation's token, which it holds in memory, as a secret, until fifteen minutes before it expires, and never logs or writes. A grant is the setup redirect's query, the installation and a code for the person who installed the App, and counts once GitHub lists the installation among that person's and its signed record of the install names that person as its installer. A write goes through the installation its caller names, once the caller finds the writing tenant connected the one that holds the repository (`installation_of`); a push hands git that token for the repository's URL alone. |
| `events/github_wire.py` | GitHub's signature (`X-Hub-Signature-256`, HMAC-SHA256 of the body) and the reading of its comments, reviews, reopened or assigned issues, check suites, statuses, and pushes; a delivery's id is the digest of the body, since GitHub signs no id and no time. `checks_state` folds GitHub's outcomes into passed, failed, or not yet. |
| `events/slack.py` | The chat as a Slack app. It posts with the app's bot token, the platform's mark in the message's metadata. A grant is the code of the app's install, and counts once Slack names its workspace for it. |
| `events/slack_wire.py` | Slack's signature (`X-Slack-Signature`, HMAC-SHA256 of `v0:<timestamp>:<body>`, a five-minute window) and the reading of its messages; its address check is acknowledged with its challenge. |
| `events.IntegrationAbsentImpl` | The integration of a process with none configured, or of a client missing a setting, which it names: every delivery and every post is unavailable, `503`. |

A client's tests run over the system's recorded deliveries and answers in
`tests/fixtures/`, and reach no network. The ones that reach GitHub or
Slack are marked `live` and run by hand (`make test-live`), never in a
gate.

## Settings

| Setting | What |
|---------|------|
| `ACME_IDENTITY_PROVIDER` | `workos`, `twin`, or `none` (the default). The twin is refused at boot outside `local` and `test`. |
| `ACME_WORKOS_CLIENT_ID` | The application's client id. Not a secret. |
| `ACME_WORKOS_API_KEY` | The application's own API key: the exchange's client secret and the key of every management call. Empty or `off` leaves WorkOS unconfigured. |
| `ACME_WORKOS_WEBHOOK_SECRET` | The webhook endpoint's signing secret, injected at start. Unset, every delivery is refused as unavailable. |
| `ACME_WORKOS_BASE_URL`, `ACME_WORKOS_TIMEOUT_SECONDS` | Where the client calls, and the timeout of every call. |
| `ACME_INTEGRATIONS` | `twin` or `none` (the default): what serves the forge and the chat. The twin is refused at boot outside `local` and `test`. |
| `ACME_FORGE_TWIN_USERNAME`, `ACME_FORGE_TWIN_PASSWORD` | The credential the forge's twin pushes with, for a repository behind basic authentication. Unset, it pushes with none. Refused at boot outside `local` and `test`. |
| `ACME_FORGE_INTEGRATION`, `ACME_CHAT_INTEGRATION` | What serves the forge (`github`, `twin`, or `none`) and the chat (`slack`, `twin`, or `none`), where it is not what `ACME_INTEGRATIONS` says. Unset follows it. A twin is refused at boot outside `local` and `test`. |
| `ACME_GITHUB_APP_ID`, `ACME_GITHUB_PRIVATE_KEY`, `ACME_GITHUB_WEBHOOK_SECRET`, `ACME_GITHUB_CLIENT_ID`, `ACME_GITHUB_CLIENT_SECRET`, `ACME_GITHUB_ACCOUNT` | The GitHub App: its id, its private key (a PEM), its webhook's secret, its OAuth client, and its bot's login, the platform's own account (`<slug>[bot]`). Without any of them the forge is absent, and says which. |
| `ACME_SLACK_BOT_TOKEN`, `ACME_SLACK_SIGNING_SECRET`, `ACME_SLACK_CLIENT_ID`, `ACME_SLACK_CLIENT_SECRET`, `ACME_SLACK_ACCOUNT` | The Slack app: its bot token, its signing secret, its OAuth client, and its bot's user id, the platform's own account. Without any of them the chat is absent, and says which. |
| `ACME_GITHUB_API_URL`, `ACME_GITHUB_WEB_URL`, `ACME_SLACK_API_URL`, `ACME_GITHUB_TIMEOUT_SECONDS`, `ACME_SLACK_TIMEOUT_SECONDS` | Where each client calls, and the timeout of every call. |

[The WorkOS runbook](../docs/runbooks/providers/workos.md) sets them up.

## The model providers

`model_providers.ModelProviderInterface` calls a hosted model, streamed.
One content shape crosses it both ways: the blocks a step's content is
made of, which live here, beneath the object model
([ADR 1005](../docs/adr/1005-the-provider-boundary-holds-the-one-content-shape.md)).
Each adapter:

- translates the shape into its provider's request and the provider's
  events back into it, and names what does not survive (`Dropped`):
  thinking another model thought, a cache marker the provider cannot
  read, a block of a kind the engine does not hold;
- keeps each thinking block's place in its turn, and replays a turn in
  the order the provider sent it;
- records why a response stopped, and marks one cut by its bound or by a
  broken stream as truncated, never whole;
- reads usage into disjoint classes: input, cache read, cache write,
  output, and thinking;
- reads a failure from its status and its message into a kind
  (`ErrorKind`), whose answer the engine owns;
- retries nothing.

The registry, `ModelProvidersInterface`, holds an adapter for every
provider. A call may carry its own credential, such as a tenant's key,
in place of the platform's.

| Implementation | What it is |
|----------------|------------|
| `model_providers/anthropic.py` | The Messages API over HTTP. |
| `model_providers/openai.py` | The Responses API over HTTP, stored nowhere at the provider, so a reasoning model's thinking comes back encrypted and replays to the model that thought it. |
| `model_providers/scripted.py` | The twin of every provider: each call takes the next turn of its script, a reply streamed in parts with its usage, or a failure of any kind, before the stream or part of the way through it. |
| `model_providers/absent.py` | The provider of a process that calls no model: every call fails as a missing credential. |

Settings: `ACME_MODEL_PROVIDERS` (`live`, `scripted`, or `none`, the
default; the scripted twin is refused at boot outside `local` and
`test`), `ACME_MODEL_SCRIPT` (the twin's script, a JSON file of each
provider's turns, read once at boot), `ACME_ANTHROPIC_API_KEY` and `ACME_OPENAI_API_KEY` (the
platform's keys; empty or `off` leaves a provider with none),
`ACME_ANTHROPIC_BASE_URL`, `ACME_OPENAI_BASE_URL`, and
`ACME_MODEL_TIMEOUT_SECONDS`.

## What every integration holds to

- **A timeout on every call**, from settings.
- **A request's deadline on every call a request makes**, shared by
  every call of the request; a worker's calls carry none
  ([ADR 0069](../docs/adr/0069-a-request-has-a-deadline-its-provider-calls-share.md)).
  The forge's and the chat's interface takes no deadline, so their calls
  carry their timeout alone.
- **One exception family.** `ProviderUnavailable` is `503`,
  `ProviderRefused` `400`, `ProviderConflict` `409`. The key never
  appears in a message.
- **A refused key is unavailable; a refused request is refused.** Work
  parks on the first and fails for good on the second
  ([ADR 0051](../docs/adr/0051-a-refused-key-is-unavailable-a-refused-request-is-refused.md)).
- **A twin that says it is one**, and is refused in a deployed
  environment.

## What a provider that hangs costs a call

Each SDK keeps its own retries. WorkOS's SDK retries a timeout, so a
provider that takes a call and never answers holds it for the timeout
on every attempt, plus the waits between them. At the default timeout
of 10 seconds:

| Provider | Attempts | Waits between them, at most | A call gives up after, at most |
|----------|----------|-----------------------------|--------------------------------|
| WorkOS | 4 | 1.5, 3, and 6 seconds | 50.5 seconds |
| A model provider | 1 | none | 120 seconds of silence |

The timeout bounds each wait on the network (to connect, to send, and
between bytes of the answer), not an attempt as a whole. WorkOS also
waits as long as a `Retry-After` on a 429 or a server error asks, with
no cap of its own. A model adapter retries nothing and waits on no
`Retry-After`: it hands the wait to the engine with its failure. A
streamed answer runs as long as its parts keep coming, and a model call
is a worker's, with no request deadline.

That is what a call costs a worker. A request makes its calls in turn,
and they share its deadline, `ACME_REQUEST_DEADLINE_SECONDS` (20
seconds) from when it was admitted, so a provider that hangs costs a
request that and no more (ADR 0069):

- a call that starts with no time left does not start;
- a call still waiting at the deadline, on an attempt, on the wait
  before the next, or on a wait the provider asked for, is cut there;
- WorkOS sends each attempt with the smaller of the timeout and what is
  left, and a `Retry-After` longer than what is left ends the call at
  once instead of being slept;
- the call then raises what it raises when the provider does not
  answer: `ProviderUnavailable` (`503 unavailable`).
