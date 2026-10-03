# ADR 2027: The forge is a GitHub App, and the chat a Slack app

**Status**: accepted (2026-10-03)

## Context

Work In, Results Out: a session's work ends as a pull request, and the
world answers on it and in chat. Until now each integration had a twin
and nothing else, so a deployed platform reached no real forge and no
real chat. Twins and Provenance keeps the twins for local and every
gating suite.

A real client meets what a twin does not. The system signs its
deliveries its own way, and some sign no time and no id. It checks the
address it delivers to before it sends an event. It hands the person who
installs the platform a grant that may be a bare id. And it writes with a
credential that must never leave the integration (ADR 2022).

## Decision

**Each integration chooses its client per environment.**
`ACME_FORGE_INTEGRATION` (`github`, `twin`, `none`) and
`ACME_CHAT_INTEGRATION` (`slack`, `twin`, `none`) choose one each, and
follow `ACME_INTEGRATIONS` when unset. A twin is refused at boot outside
`local` and `test`. A client missing any of its settings serves as
absent, and the boot log names what it lacks.

**The forge is a GitHub App.** It signs a JWT with the App's private key
and trades it for an installation's token. The token is held in memory,
as a secret, until fifteen minutes before it expires: longer than a
push's git commands may take. It is never logged, written, or put in a
message. A write goes through the installation that holds the
repository, and only once the session's own tenant connected it: one App
serves every tenant, so its token would reach another tenant's
repository. The platform refuses any other before anything is written,
and a push hands git the token for that repository's URL alone.

**A delivery is checked before a byte of it is read.** GitHub signs the
body alone, with no time and no id, so a GitHub delivery's id is the
digest of the body it signed. A replay, or a header that names another
id, is the same key. Slack signs a timestamp with the body, and a
delivery outside five minutes is refused. A delivery that checks out and
is the system's check of its address (GitHub's ping, Slack's challenge)
is acknowledged: answered, and never queued. Any other delivery that is
no event the router reads is refused.

**A grant counts once the system confirms the person.** GitHub's setup
redirect names an installation in a query anyone can type, so the grant
also carries the installing person's code. The code is traded for that
person's token, and the installation counts only when GitHub lists it
among the ones they may reach and its signed record of the install, the
`installation` delivery it sent the App, names that person as the
installer. Another member who may reach the installation cannot connect
it first. Slack's grant is the code of the install,
and the workspace is the one Slack names for it. What either trade
answers besides is used once and kept nowhere.

**The platform's own account is a setting.** The App's bot login and the
Slack bot's user id name the platform's acts, so they never wake a
session. A person is named by the system's stable id, never a login a
rename can free.

## Consequences

- A deployed environment opens real pull requests and posts to real
  chat once its settings are set; until then it serves both as absent.
- Every gating suite still runs the twins, and the clients' tests run
  over recorded deliveries and answers. A test that reaches GitHub or
  Slack is marked `live` and runs by hand.
- The ingress's answer carries a `challenge` when a system asks one.
- The chat posts with one bot token, so it reaches the workspace that
  token was made in, and a grant from any other workspace is refused.
- A write reaches only a repository an installation the writing tenant
  connected holds. The client writes through the installation it is
  named; the platform finds the tenant, where a project binds a
  repository and intake maps an installation to its tenant.
- An installation is connected while GitHub still lists the record of
  its install among the App's recent deliveries; one installed long
  before is installed again to connect it.
