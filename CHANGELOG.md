# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.25.0 (2026-10-21)

The platform's base moves to the engine's v0.21.0, with the guideline's
v0.63.0: a person signs in through the identity provider alone, on
every stack, and nothing keeps a password. The browser checks sign
their people in from the local mint. Minor, with one reversal: the
sign-in by an address alone is gone.

### Added

- From the base: `acme-api mint-local-login`, the local mint, which
  prints a sign-in token for each address from the local database and
  refuses at boot outside `local` and `test`, with no route and no page;
  and the engine's demo played as a scene (#187).

### Changed

- The base moves to the engine's v0.21.0 and the guideline's v0.63.0.
  Every stack signs in through WorkOS, the local one through the Staging
  application. `make seed` makes each seeded person a plus-address of
  `SEED_EMAIL` in `.env` and refuses a domain that takes no mail; an
  existing checkout sets it and runs `make reset`. The spec and lenses
  cite both releases (#187).
- The browser checks sign each person in from one `mint-local-login`
  run per spec: the login is exchanged for an auth session in the org
  and put in the portal's session before the page loads, and no page
  signs anyone in. The platform's own tests sign in through the
  identity twin (#187).
- The WorkOS runbook, ADR 0063, and the WorkOS client name every
  sign-in method: an email code, Google, Microsoft, Apple, GitHub, and
  single sign-on (#187).

### Fixed

- `portal_check.py tree` reads the agent's steps from
  `managers.agent_steps` (#187).

### Removed

- From the base, the sign-in by an address alone:
  `POST /v1/auth/dev-sign-in`, `ACME_DEV_SIGN_IN_ENABLED`, the portal's
  `/login/dev`, and `--dev-email` (reversal) (#187).
