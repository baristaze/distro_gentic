# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.27.0 (2026-10-23)

The platform's base moves to the engine's v0.23.0, on the guideline's
v0.65.0: a host's and a claimant's calls that keep what they hold go
through under load, and every file and output an exec item moves
crosses the store by a URL signed for it alone. A claimant is woken by
push. Minor, with the base's reversals: the presigned POST and the
presign that may answer `None` go, and CTX-07 allows a second context
variable. The exec wire moves to version 2, and a host of an earlier
release is refused.

### Added

- A product's claimant has a control stream of its own,
  `GET /v1/claimants/me/control`, as a host has. It says `wake` on work,
  `revoke` when an item leaves its claim, and `appended` when a stream
  its kind reads grows. The kit gains `listening()`, `wait()`,
  `revoked(item)`, and `appended(...)`, and keeps no report of a revoked
  item, which runs again. `KindStreamsInterface.append` takes `org_id`.
  ADR 2065 (#195).

### Changed

- The base moves to the engine's v0.23.0, on the guideline's v0.65.0.
  `HOLDER_CALL` marks a host's heartbeat, an exec item's renewal and
  result, its workspace answers, and a claimant's renewal and report;
  output parts, appends, and claims stay writes. A host's and a
  claimant's credential spend the lane's budget. The API pool falls to
  5 at XS and 8 at S, so the reserves fit the connection budget. Every
  blob crosses by a presigned URL, as a multipart upload (#196).
- An exec item and its result carry no file and no output. Each crosses
  the `tool-outputs` bucket as an object sealed under its own key, kept
  under the session's key, by URLs signed for it alone: a GET, or the
  parts of a resumable multipart upload. The host moves objects off its
  lease loop, spooled on disk, and writes nothing whose digest and size
  do not match. A write's file leaves at its item's settle, an output at
  its session's purge. A result sent again keeps what its first push
  completed, and a call whose output was not kept fails as interrupted.
  `RESULT_CHARS` falls to 62,698, and relayed reads are no longer cut at
  8 MiB. The exec wire and its floor move to 2. ADR 2066, PLC-22 (#197).
- The scaffold's `host` job starts beside the fast gate (#193).

### Fixed

- A host keeps the leases it holds while it reads a large item or
  snapshots a workspace: an exec item's lease is renewed from its claim,
  and a snapshot's scan, digest, and archive run off the host's loop,
  the archive held once (#194).
