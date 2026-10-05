# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.5.0 (2026-10-05)

A claimant reads the streams its kind reads for the item it holds; a
head cannot rewrite what scores the hidden suite while it runs; an API
key decides no held call and starts a validation only at its own role;
a refused validation reads refused; one tenant's bad retention policy
stops no one else's sweep; a removed person's links go; and the
platform builds on the engine at v0.5.1. Minor: a route, a stream
kind's `reader`, and a validation status are added, a key's decision is
refused where it was stored as a program's, and a product's kinds may
need a `reader` on a stream its claimant reads.

### Added

- `GET /v1/claimants/me/items/{item_id}/streams/{kind}?after=` reads an
  item's streams of a kind whose `reader` is the claimant's own kind, for
  the item it holds under its token with a live lease; any other item,
  kind, tenant, or a lapsed lease is the same 404, and each read spends
  the credential's read budget. `ProductKinds` refuses at boot a
  `reader` that is not one of the product's claimant kinds. ADR 2038
  (#88).
- A validation session the worker refuses for good reads `refused`, with
  its reason, `passed` false, and no run; a core migration adds its
  `refusal` (#90).
- `make stop` and `make start` beside `up` and `down`, from the engine's
  base at v0.5.1 (#93).

### Fixed

- A head's code runs with every file the suite protects read-only, and a
  digest of those files after each trial errors a trial that changed
  one, so a head that rewrites and restores what scores the suite has no
  verdict; a check may still write new files beside its protected ones
  (#89).
- The retention sweep folds each tenant's snapshots on its own: a fold
  that fails waits out of the read until its next attempt or its next
  held expiry, and a policy's lifetime past a century is refused where
  it is written (#87).
- A member's removal and an account's deletion forget the person's chat
  and forge links in that tenant, each with its audit written first; a
  GitHub 403 for its secondary rate limit is a wait, as a 429 is (#91).

### Changed

- A decision on a held call whose actor is an API key is refused, and
  the call stays held; a validation session keeps the key it was started
  on and runs at its starter's live role, capped by that key, refused
  when either no longer holds. A core migration adds its `key_id`.
  ADR 2039. Reversal: a key's decision was stored as a program's
  (#92).
- The base is agentic_core at v0.5.1, on the guideline at v0.51.1 (#93).
