---
name: distro-deviate
description: "Record a deliberate deviation from a rule of the distro_gentic spec as an ADR: the rule quoted, the decision, the consequences. Use when a finding of a platform review is accepted as intentional."
allowed-tools: Read, Grep, Glob, Write, Edit, Bash(date:*), Bash(git ls-tree:*)
---

# distro-deviate

Code built on the platform may still need to diverge from a rule of
the spec. The divergence is recorded, not argued about in review
threads: one ADR quotes the rule, states the decision, and names what
the repository accepts in exchange. A breach whose ADR is cited next to
the code is a documented exception. A platform review
(`distro-review-<group>`) reports it on one line under Deviations. It
is not a finding, and it never lowers a severity.

## Input

The arguments name the rule being deviated from, as a lens id
(`PLC-02`), a section of the spec by title (`Money, Metering and
Limits`), or a sentence describing it, optionally followed by a one-line
reason. Ask in one message for what is missing: the reason, the scope
of the deviation (which namespace, host, runner, or agent kind), and
whether it is permanent or has a condition for ending.

Four things are no deviation from the spec. When the arguments describe
one, say which, and stop:

- A rule of the engine: a lens id of the engine's (`STP-02`), or a
  section of the engine's spec. The engine's own `agentic-deviate`
  records it.
- A rule of the guideline: a lens id of the guideline's (`STO-02`), or
  a section of the guideline. The guideline's own `arch-deviate`
  records it.
- A section tagged `default`: a named choice an adopter may substitute.
  Only a departure from untagged text is a deviation.
- A section tagged `core`: an invariant, and a departure from it is a
  different platform, never a deviation.

A lens id is the platform's when its prefix is in the group table of
`../../lenses/README.md`, a path from this skill's folder as `realpath`
resolves it; any other prefix is a layer's beneath.

## Procedure

1. Resolve the rule: find the lens in `../../lenses/` and the section
   it cites in `../../distro_gentic_spec.md`. Quote the principle
   verbatim: the lens's Principle, or the section's Principle box when
   no lens holds the rule. Read the tag alone on the line under the
   heading that states the rule, if any: a tag covers its own heading's
   text, never the subsections under it. A lens's first Source is the
   section that states its rule, so when a lens cites several sections,
   the first one's tag decides. When the rule itself allows what the
   arguments describe, such as an `optional` section whose trigger has
   not arrived, there is nothing to record: say so, quote the words
   that allow it, and stop.
2. The ADR goes in the repository's records folder, where a review
   opens it by the number cited beside the code:
   `scaffold/acme_root/docs/adr/` when the repository holds
   `scaffold/acme_root/`, as the platform's own does; else `docs/adr/`
   at the root of the repository you run in, as a copy of the scaffold
   has it. Create the folder when it does not exist. A repository's own
   records take a thousand no layer beneath it uses, so a later release
   of its base never brings the same number. The records the base holds
   are upstream: the files of a `docs/adr/` folder on the `scaffold`
   branch, wherever in that tree the base keeps it
   (`git ls-tree -r --name-only scaffold`, or `origin/scaffold` when
   there is no local branch). The repository's thousand is the next
   above the highest upstream number. The guideline's records are below
   1000 and the engine's 1001 to 1999, so the platform's own are 2001
   to 2999, and a project built on the platform numbers from 3001. The
   new record is one above the highest record already in that
   thousand, or its first number when there is none. When there is no
   `scaffold` branch, say so and stop: only the base tells an upstream
   number from the repository's own. Zero-pad the number as the
   folder's records are (`NNNN-<slug>.md`, the slug the title's words
   in lowercase, joined by hyphens). Refuse to write a path that
   already exists.
3. Take the date from `date +%F`: the ADR records the day the decision
   is made, which is today, not the day of the last commit.
4. Write the ADR with the template below, in the records folder only.
   Keep it under one page.
5. Append one row, the ADR number, the rule, and a one-line summary, to
   the `## Deviations` table that holds the platform's deviations. It
   is the table of a file under the `specs/` folder beside the records
   folder's `docs/` that names `distro_gentic_spec.md`: when more than
   one does, the one whose table already holds rows of the repository's
   thousand, else `specs/architecture.md` when it is one of them, else
   the first of them in path order. When no file there names this
   spec, the row goes in the `## Deviations` table of
   `specs/architecture.md` there, which holds the rows the layers
   beneath brought. When there is no such table, there is no deviations
   table.
6. A `distro-check` entry goes only with a finding the checker reports.
   The lens's `Check` line says which part that is: the whole lens when
   it reads "decides it", and only the part it names when it ends "the
   rest is judged". The rule's docstring says exactly what it reads:
   the function under `@rule("<LENS-ID>"` in
   `../../scaffold/acme_root/checkers/src/acme/distro_check/rules/<group>.py`,
   the group the lens's file names. Read it, and give an entry only
   when the deviating code is what it reads, in the modules it reads. A
   deviation in a judged part, or under a lens whose `Check` line reads
   `review`, gets no entry: the checker reports nothing there, and an
   entry that matches no finding is itself a finding that fails the
   gate. The ADR, the Deviations row, and the citation beside the code
   are its record. For a deviation in the part the checker decides, the
   ADR alone does not pass the gate: give it the entry that names the
   ADR, in the shape the copy's `checkers/README.md` shows (Exceptions;
   `scaffold/acme_root/checkers/README.md` in the platform's own
   repository), whose rule id is the lens id. A whole rule turned off is
   a `[[tool.distro-check.disable]]` entry with `rule`, `adr` (the ADR's
   path), and `reason`. A rule broken in some files is a
   `[[tool.distro-check.exception]]` entry with `rule`, `path`, `adr`,
   and `reason`. Its `path` is a glob from the copy's root over the
   files the scope covers and no more: a module is its own path; a
   namespace is its folder followed by `/**`; a host, a runner, or an
   agent kind is the module that defines it, and a scope of several
   modules is one entry each. `*` stays inside one folder, and `**`
   spans folders. Append it to the copy's `pyproject.toml`
   (`scaffold/acme_root/pyproject.toml` in the platform's own
   repository, the root's in a product) when that has a
   `[tool.distro-check]` table, and print it otherwise. Write no inline
   ignore comment: the checker reads none.
7. Tell the person to cite `ADR-NNNN` in a comment beside the code that
   deviates. A review reports the code under Deviations, and not as a
   finding, only when the ADR is cited there.

Do not commit. Do not edit the spec or the lenses; a deviation belongs
to the repository that makes it, not to the rule. Edit nothing but the
records folder, the deviations table, and the checker entry.

## Output

The path of the new ADR, the row appended to the deviations table (or
"no deviations table"), the checker entry appended or printed (or "no
checker entry"), the reminder to cite `ADR-NNNN` beside the code, and
the one-line summary for the reviewer. Nothing else.

## ADR template

```markdown
# ADR NNNN: <title that names the deviation>

**Status**: accepted (<date>)

## Context

<The rule: lens id, section of the distro_gentic spec, and the principle
quoted verbatim. Why it does not fit here. Facts, not preferences.>

## Decision

<What the repository does instead, in the present tense. Where it
applies. Whether it is permanent or ends when a named condition holds.>

## Consequences

<What the repository accepts: the guarantee it gives up, the test or
check that stands in for it, the reviews that must treat the cited code
as an exception.>
```
