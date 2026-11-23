# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.32.0 (2026-11-23)

The platform's base is the engine at v0.28.0, so a person's view of a
session names the engine's notices and shows a failed call without the
advice meant for the model; and the local stack runs the cloud pool on
Lima. Minor, with three reversals named below.

### Changed

- The base moves to the engine's v0.28.0: a response's calls run one
  after another in the order the model made them, a call that waits for
  a person put off until the person decides; the step view gives a
  failed call's text as the tool's own, without the advice the model
  reads, and the CLI prints a notice the engine wrote as
  `from the engine: ...`; the portal shows a failed call's answer as
  the tool's own text. Reversal: a client that read the advice from a
  failed call's `text` in the step view no longer finds it there
  (#229).

### Added

- The local stack runs the cloud pool on Lima: `make cloud-pool` names
  or builds the pool's image and runs the runner on the host with the
  pool on, and `make cloud-pool-session` starts one session in a VM.
  `ACME_CLOUD_POOL_S3_ENDPOINT_URL` names the address a pool VM reaches
  the store at, apart from the browser's, and the exec relay signs a
  pool VM's links for it; every other host gets the browser's. The
  local app containers take `ACME_KEYS_ROOT_KEY` from `.env`. The
  pool's image installs ripgrep (#228).

### Removed

- A tree's concurrency bound, which nothing held: the engine's
  `TreeLimits.concurrency` and `AgentTree.concurrency`, and the
  platform's bounds view's `tree.concurrency`. Reversals: a kind whose
  tree names it no longer builds, and the bounds view no longer carries
  it (#229).
