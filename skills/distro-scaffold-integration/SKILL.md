---
name: distro-scaffold-integration
description: "Add a real client of an external system for one of the platform's integrations, with its twin: the signature check and the reading of a delivery into the platform's terms that both share, the client's posts, the twin's synthetic deliveries in the system's wire shapes, provenance on every record, the setting that selects them, and their tests over recorded fixtures, in the shape of the identity provider and the integrations' twin. Python."
allowed-tools: Read, Grep, Glob, Write, Edit, Bash(make check), Bash(uv run:*), Bash(git status:*), Bash(git show:*)
---

# distro-scaffold-integration

A path that starts with `../` is read from this skill's folder as
`realpath` resolves it.
Conventions: `../_shared/scaffold-conventions.md`.
Sections of `../../distro_gentic_spec.md`: Work In, Results Out (Intake,
Feedback Routing, Twins and Provenance), Evidence (Execution Records),
Trust (Untrusted by Default).
Lenses: `../../lenses/intake.md`, and `../../lenses/evidence.md` for
provenance.

## Input

`<integration> --system <system> [--post <endpoint>]`, and how the
system signs a delivery, what its deliveries look like, and how a
message is posted to it, in the arguments or in the conversation.

Example: `forge --system tinyforge`, for "a self-hosted forge: it signs
a delivery with HMAC-SHA256 of the body in `X-Tinyforge-Signature`,
names the event in `X-Tinyforge-Event` and the delivery in
`X-Tinyforge-Delivery`, and takes a comment at
`POST /api/repos/{repo}/issues/{number}/comments`".

- `<integration>` is a name in `INTEGRATIONS` in
  `integrations/src/<name>/integrations/events/__init__.py`, such as
  `forge` or `chat`. A name not there is a change to the platform's
  intake, not this skill's: stop and say so.
- `<system>` is the external system, snake case. `<System>` is its
  CamelCase, and `<SYSTEM>` its upper snake case.
- What the system sends and takes: when it is not given, ask;
  unattended, read it from the system's public documentation when the
  machine reaches it, else decide it, and name the choice. Either way
  the recorded fixtures of step 6 hold it.

## Created

The shape of a client with its twin is the identity provider,
`integrations/src/<name>/integrations/identity/`: the real client
`workos.py`, the twin `twin.py`, and the signature check both share,
`deliveries.py`. The shape of an integration is
`IntegrationInterface` in `integrations/src/<name>/integrations/events/__init__.py`,
and of its twin `IntegrationTwinImpl` in `events/twin.py`.

| File | Holds |
|------|-------|
| `integrations/src/<name>/integrations/events/<system>_wire.py` | the system's signature check and the reading of its delivery into a `ProvidedEvent`, which the client and its twin both call |
| `integrations/src/<name>/integrations/events/<system>.py` | `<System>Impl(IntegrationInterface)`, the real client, over `httpx` |
| `integrations/src/<name>/integrations/events/<system>_twin.py` | `<System>TwinImpl(IntegrationInterface)`, the system's twin, with `deliver` for tests and the local stack |
| `integrations/tests/fixtures/<system>/` | recorded deliveries, each with its headers, and recorded answers to a post |
| `integrations/tests/test_<system>.py` | the cases of step 6 |

## Changed

| File | Change |
|------|--------|
| `integrations/src/<name>/integrations/settings.py` | `<integration>_integration: Literal["<system>", "twin", "none"] \| None = None`, and the system's settings: its base URL, its timeout, the platform's own account on it, and its secrets as `SecretStr \| None` in `_key_off_is_none` |
| `integrations/src/<name>/integrations/impl/configured.py` | in `integrations_for`, `<integration>` served by `<System>Impl` or `<System>TwinImpl` as its setting says, else as `integrations` says; in `refuse_unsafe`, the system's twin refused when deployed |
| `.env.example` | `ACME_<INTEGRATION>_INTEGRATION` and the system's settings, commented, with `ACME_` read as the tree's prefix; a secret's line names the variable, never a value |
| `integrations/tests/test_configured.py` | the cases of step 6 for the setting |
| `deployment/terraform/modules/secrets/main.tf`, `outputs.tf`, `deployment/terraform/modules/environment/main.tf`, `deployment/terraform/modules/README.md` | each secret of the system, shape `workos_api_key`: a secret, `off` until set, injected as `ACME_<SYSTEM>_<KEY>` into the processes that build the integrations; each other setting given its value in the environment's `process_environment` (`modules/environment/main.tf`), the map every process shares, the maintenance worker's included |
| `services/api/tests/test_settings.py`, `workers/maintenance/tests/test_settings.py` | a setting whose local default serves the cloud, in `LOCAL_DEFAULT_SERVES_THE_CLOUD` with its reason, as `workos_base_url` is |
| `integrations/README.md` | the client and its twin in the table of The integrations, and their settings |

## Procedure

1. The ingress takes every integration's deliveries at
   `POST /webhooks/integrations/<integration>` and asks the integration
   this process holds (`get_integration`) to check and read each one. So
   a client adds no route, no queue, and no mapping to the router: it
   answers `verify_delivery` with a `ProvidedEvent`, and the platform
   does the rest. An arrival is one the router reads, in its terms
   (Feedback Routing); the system's own event names stay inside
   `<system>_wire.py`. `installation` is the tenant's org id, as
   `event_of` in `om/src/<name>/om/intake/rules.py` reads it (a UUID):
   the wire sends the org id, and nothing maps a real system's own
   installation or account id to an org, so the report names that gap
   for a real system's deliveries. An
   author is `platform` when the system names the platform's own
   account, which a setting of the system names: the router reads that
   kind as the session's own act (`effect_of`), so a comment the agent
   posted never wakes it. Every other author is `person` or `bot`, as
   the system says.
2. `verify_delivery` checks the signature over the body before it reads
   a byte of it, in constant time, with the system's secret, and refuses
   a stale one when the system signs a timestamp. A delivery that fails
   the check, names no delivery id, or is no event the router reads,
   raises `DeliveryRefused`, naming what failed and never the secret.
   Its key is `delivery_key(<integration>, <the system's delivery id>)`,
   so a retried delivery is one event. The body is data: no field of it
   decides who the author is beyond what the system signed, and none
   decides what served it.
3. Provenance is the integration's word, never the delivery's. The real
   client's `provenance` is `real`, and every `PostedMessage` it answers
   says `real`. The twin's is `twin`, every record it writes says
   `twin`, and every id it mints starts with `twin_`, as
   `IntegrationTwinImpl` does. A body that claims a provenance is read
   as nothing.
4. The twin speaks the system's wire shapes, never the platform's:
   `deliver(...)` builds a body as the system sends one and signs it with
   the system's scheme under a twin secret, so `verify_delivery` runs
   the same code in `<system>_wire.py` as the real client's does. It
   records every message posted through it, in order, as `posted`. The
   configured root refuses it outside `local` and `test`, as it refuses
   every twin.
5. `post(address, text)` reaches a person: `address` is their account
   on the system, the `external_id` of their account link, as the
   notifications manager passes it (`om/src/<name>/om/notifications/impl/manager.py`).
   The real client posts through `httpx` with the timeout its settings
   name, and maps a refused key to `ProviderUnavailable`, never to a
   person's error, as `integrations/README.md` lists under What every
   integration holds to. Every exception it raises is one of
   `integrations/src/<name>/integrations/exceptions.py`. Without its
   token or its webhook secret, `integrations_for` serves the absent
   integration, `IntegrationAbsentImpl`, as WorkOS without its key is
   absent. An SDK, when one is needed at all, is pinned exactly in
   `integrations/pyproject.toml`. A deployed process reads every setting
   from its environment's Terraform, and
   `test_every_setting_the_cloud_needs_is_wired` fails on one the cloud
   sets no value for and no reason excuses.
6. The tests reach no network. The real client's run over the recorded
   fixtures and a fake transport, shape `integrations/tests/test_identity_workos.py`;
   the cases that hold for both run once over the client and once over
   its twin, as one parametrized test:
   - a recorded delivery checks out and reads into the `ProvidedEvent`
     the fixture names; a second read of it has the same key; one whose
     author is the platform's own account reads as `platform`;
   - a delivery with a tampered body, a wrong signature, no signature,
     or, when the system signs one, a stale timestamp is refused, shape
     `test_a_delivery_that_does_not_check_out_is_refused` in
     `integrations/tests/test_integration_twin.py`;
   - a body that claims a provenance is still the integration's, shape
     `test_a_body_that_claims_to_be_real_is_still_the_twins`;
   - a post answers a `PostedMessage` with the integration's provenance,
     and the twin records it; a post the system refuses with its key is
     `ProviderUnavailable`;
   - the setting selects the client or its twin, the twin is refused in
     a deployed environment, and the client without its secrets is
     absent, shape `test_the_twin_is_refused_in_a_deployed_environment`
     and `test_workos_without_its_key_is_absent` in
     `integrations/tests/test_configured.py`.

Then the gate, `make check`, as After writing in the conventions
runs it.

## Output

As `../_shared/scaffold-conventions.md` states, and the address the
system delivers to: `<api>/webhooks/integrations/<integration>`.
