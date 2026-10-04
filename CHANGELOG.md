# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.2.0 (2026-10-04)

The platform's routes and screens, a product's own kinds of work, a
deployment ready to ship, and the engine at v0.3.0. Minor: rules are
added, and no released rule is reversed.

### Added

- Routes for a session's reads and its evidence (#50); for projects and
  repositories, knowledge and playbooks, automations, and tool policies
  (#52); and for the model matrix, a tenant's provider keys, and the
  operators' reads of benchmarks and ledgers (#51).
- The portal shows a tenant its sessions: the list, a new session in a
  project, and the session page, with the design kit's views (#57). It
  keeps a tenant's records and settings: projects, models and keys,
  automations, playbooks, knowledge, approvals, audit, and usage, a
  credential or key never shown back (#61).
- A product adds its own kinds: work kinds, claimant kinds, lanes, secret
  owners, stream kinds, and validation executors are registries the
  platform's own kinds go through (#55). A product's parts reach every
  process from one declaration, and a hidden suite runs from its own
  repository, protected (#59). A product's claimant enrolls and claims
  through the gateway, as a host does (#60), and streams the item it
  holds, each entry verified by its hash, read by a member through a
  handle (#62).
- The engineer edits a file by one place and searches its code, and
  agents search, read, and suggest knowledge (#56).
- A real forge and chat behind their twins: a GitHub App and a Slack
  app, each write and connect held to its tenant (#54).
- The deployment is complete: the session runner runs in the cloud, and
  a host installs as a hardened service (#53).

### Changed

- The scaffold base moves to the engine at v0.2.0 (#58) and then v0.3.0
  (#63): a tool's long job parks its loop, the platform's gates hold and
  settle its spend, and `read_attachment` reads past a long line.
