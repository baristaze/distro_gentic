# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.11.0 (2026-10-08)

A kind's claimant takes the platform's hardening whole, with the groups
its kind grants; the kit keeps a credential live through a long work;
the work-kind skill builds a product's claimant on the kit; and the base
is the engine at v0.10.0, whose account mode runs under a hardened unit
and whose transport reads from an offset. Minor: a relayed read carries
an offset past the start, and a kind's drop-in may grant groups;
nothing is reversed.

### Added

- `own-group-only.sh` takes `--granted` for each group a kind's unit
  grants, and refuses any other group beyond the user's own;
  `install.sh` reads the grants a kind's hook writes in its drop-ins
  from systemd and passes exactly those. A granted group opens only
  what the unit lets the claimant see: a written path outside the state
  directory, /home, and a device stay the kind's own drop-in (ADR 2047,
  #124).
- `Claimant.keeping_alive()` rotates a credential that falls due while
  a work runs, so a work past half the credential's life no longer
  leaves its claimant refused; a work opens `claimant.client()` per
  call or short burst, never across a beat (ADR 2046, #127).
- A relayed read carries its offset to the host, past the start only,
  and the host echoes it; an answer that does not echo it is refused,
  never handed back as the bytes after the offset (#128).
- A claude.ai run of `browser-judge-distro` on 2026-10-08, with its
  permission mode at Auto, at sizes `m, m` on v0.10.0: 70 (#126).

### Changed

- `distro-scaffold-work-kind` writes a new claimant kind's program on
  the claimant kit, inside `keeping_alive()`, and its install over the
  shared installer with the kind's names; `--grants` writes the kind's
  groups in its drop-in. The product keeps its work, which imports the
  client and the kit alone (#125, #127).
- The base moves to the engine at v0.10.0 (#128): the account mode runs
  under a unit with `ProcSubset=pid` and `RestrictSUIDSGID=yes`
  (`ACME_WORKSPACE_PROTECTED_HARDLINKS` declares the setting where the
  unit hides it), `read_file` takes an offset in every transport, and a
  command is over when its own process exits (ADRs 1021, 1023). The
  lenses cite the engine at v0.10.0.
