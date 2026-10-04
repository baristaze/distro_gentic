# ADR 2010: Content opens by a grant of its own, and a tenant's secrets are its configuration

**Status**: accepted (2026-10-02)

## Context

The spec's Operator Access makes opening a session's content take an
operator permission of its own, which `read` never implies: shape is an
operator's to read and content is not, by default.

The operator plane carries one permission a token, `read` or `write`,
and the allowlist entry is a role that holds them (ADR 0018). Neither
fits. A new value of the role would need a token of its own for every
content read, and the grant job could not narrow it to one tenant. And
`write` includes `read`, so anything `write` implied would reach every
tenant at once.

The spec puts a tenant's secrets and provider keys in the platform's
hands. The engine asks `manage_keys` of a call that binds a secret
reference (ADR 1012), and every member holds `manage_keys`, to manage
the keys they sign in with. A member who could set the tenant's
provider key would send every session's content to a provider account
they hold.

## Decision

**Content opens by a grant.** The trust namespace keeps a content grant:
one operator identity, one tenant, until it expires. Reading a session's
content on the operator plane takes `read` and a live grant in the
tenant it names. Neither `read` nor `write` implies one. The grant job
writes and ends grants (`grant_content`, `revoke_content`), as it writes
the allowlist; no route does. A grant lasts an hour unless the job asks
for less, and never more than eight. Each grant, each end, and each
opening is an entry in the tenant's own event stream.

**A tenant's secrets and keys are its configuration.** Declaring a
secret, giving a cloud secret its value, and saving a provider key ask
`manage_members`, the permission that writes the tenant's own
configuration, as its tool policy does. Reading the names and the
records asks `read`. No call returns a value.

## Consequences

- An operator who must read a customer's content asks for a grant in that
  tenant, and the customer sees it, its end, and every opening.
- A support agent's token reads shape in every tenant and content in
  none, whatever it is told.
- A member manages the keys they sign in with and no secret of the
  tenant's; an admin or the owner does that.
- The grant job writes and ends a grant by the operator's email and the
  tenant's id (`acme-api grant-operator --grant-content`,
  `--revoke-content`), and the operator plane opens content at
  `/v1/admin/orgs/{org_id}/sessions/{session_id}/content`.
