# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.29.0 (2026-11-09)

A hidden suite runs the head's code apart from what scores it, an
enrollment token issued on an API key enrolls only while the key holds,
a product names its own section of the object model for the assistant,
and the README opens on the portal running a tree of sub-agents. Minor,
with two reversals: a hidden check that declares no head part is
refused, and `docs/object-model.md` no longer asks a product to add its
section below the platform's.

### Changed

- A check may declare `head`, a command that runs the head's code
  first, as a user of its own (`65534:65534` by default) that writes
  only in its trial's `{work}`. Its runner then runs as the instance's
  own user in a copy of the protected files outside the head's tree, so
  its tools load nothing the head left there, and it scores from what
  the head's user cannot write. A hidden check that declares no head
  part is refused: a one-command hidden suite moves its head's code into
  `head`. `CommandSpec.user` names a numeric user, which a container
  runs with `docker exec --user`; the local, account, and VM transports
  refuse it, so a hidden suite runs in a container. The relay carries
  the user, left off the wire when there is none; exec work moves to
  wire version 3, floor 2, and an older host never gets a command that
  names one. ADR 2067, the spec's acceptance paragraph, and EVD-12 say
  the head part leaves answers, never verdicts (#211).
- An enrollment token records the API key it was issued on, in a column
  a core migration adds. Its redeem reads the issuer's live context
  capped by that key, so once the key is revoked or expired, or caps the
  issuer below the members permission, the token enrolls no host and no
  claimant. A token issued in person enrolls as before (#210).
- `docs/object-model.md` no longer asks a product to add its section
  below the platform's: a product writes its own document, lists it for
  tenant users in the knowledge map, and names it in its slot (#208).

### Added

- `ProductKinds.object_model` names the document of a product's own
  section of the object model. The platform assistant's current version
  gets one prompt naming it, after the platform's own, and a slot naming
  a document its corpus does not hold is refused at boot (#208).
- The TypeScript client's hosts facade, `hosts`: `PoolView`,
  `CreatePoolRequest`, `ClaimantView`, `EnrollmentTokenView`,
  `IssueEnrollmentTokenRequest`, and `IssuedEnrollmentTokenView` (#206).
- `demo/`, outside the scaffold: `make demo-gif` drives a copy's portal
  through one scene, a software engineer whose four sub-agents ask their
  person, start their own, report, and roll up, and records
  `demo/tree.gif`, which the README opens on (#213).
- The platform's CI copies the scaffold and runs `terraform test` in
  each root and module of the copy that holds a test (#207).

### Fixed

- A call cancelled while its relayed send is under way, after its
  item's row landed, sends the item its stop, so no host runs it (#212).
- The exec relay's settle case cancels its write once the runner waits
  on it, and holds the file's removal with no wall-clock poll (#209).
