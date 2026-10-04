# ADR 2001: The base is the engine's scaffold, taken whole

**Status**: accepted (2026-10-02)

## Context

The platform builds on the engine, and the engine on the guideline. The
engine's scaffold holds the guideline's at the release the engine pins,
with the engine's layer inside it, so one base carries both and a second
would repeat one. The guideline numbers its decision records from 0001
and the engine from 1001; either can add one with a release.

## Decision

The scaffold is taken whole. The repository's `scaffold` branch holds
the engine's `scaffold/` folder unchanged, at the engine release the
platform builds on, and main merges it. Nothing is cut: the engine's
namespaces, checker, storage, and infrastructure impls stay, and a
product drops what it does not need.

The platform moves by `agentic-upgrade-scaffold`, one engine release at
a time, each taking the guideline release that engine release pins. Its
own decision records are numbered from 2001.

## Consequences

- The engine's next release, and the guideline's it pins, arrive by one
  merge. A merge commit keeps the base, never a squash.
- A product takes one base, which holds the engine's and the
  guideline's.
- The platform's own migrations follow the engine's: the first of each
  role's own chain takes that role's scaffold head as its parent.
- The three ranges never share a number, so a merge never renumbers a
  record.
