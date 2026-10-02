---
name: distro-explain
description: "Explain how the distro_gentic spec applies to a question, a rule, a file, or a change, citing the sections and lenses that govern it and the reasons the spec gives. Use when onboarding to platform code or before a change that crosses its parts."
allowed-tools: Read, Grep, Glob
---

# distro-explain

Answer a question about the platform with the spec as the source of
truth, not with general opinion. The spec is at
`../../distro_gentic_spec.md` and the lens catalog at `../../lenses/`,
paths from this skill's folder as `realpath` resolves it. If either is
missing, stop and say the installation is incomplete.

## Input

The arguments are one of:

- a question ("who pays when a tenant brings its own provider key?",
  "may the platform open a connection into a customer's wall?");
- a rule or a section: a lens id (`WAL-06`), or a section by title
  (`Evidence, The Result Gate`);
- a path to a file or folder in the current repository ("explain what
  rules apply to this host's module");
- a description of a change ("I want a host that runs work on a
  customer's own machines").

Empty arguments mean: give the guided tour. The Core first, one line
for each invariant, then every section in the order of the spec's
Contents, two sentences each, then the nine lens groups in one line
each.

## Procedure

1. Read The Core, the spec's Contents (the list under its `## Contents`
   heading), and the lens group table in `../../lenses/README.md`.
2. Find the sections and subsections that govern the question. A lens
   id names its group by its prefix, in that table, and its `Source`
   line names the sections it rests on. Read them in full; quote the
   `Principle` boxes verbatim when they answer the question directly.
   Name a section's tag when it has one (`core`, `default`, `optional`,
   `style`), as How to Read This in the spec defines it: it says
   whether the rule bends.
3. Give the reasons the spec gives: the sentences around the rule that
   say why, and the invariant of The Core it serves, when it serves one.
   A reason the spec does not state is not given.
4. Find the lenses that a reviewer would apply. Name them by id. When
   a lens has a `Shape` line, name the scaffold file it points to,
   `../../<path>`, and read it: it shows the rule as code, and pointing
   at it beats describing it.
5. When the question is one of general software design, or of one
   agent's loop, the spec defers to the guideline or the engine and
   repeats neither. Name the section of theirs the spec cites there
   (its links are pinned at the release the platform builds on), and
   point at the guideline's `arch-explain` or the engine's
   `agentic-explain` for the rest.
6. When the input is a path, open the code and say, for each rule that
   applies, whether the code follows it, in one line each. Do not run
   a full review; point at `distro-review-<group>`
   (`/distro-gentic:distro-review-<group>` when installed as the
   plugin) for that.
7. When the input is a change, say which section and lens group each
   part belongs to, and which lens a review of it would apply first.
8. When the spec is silent on the question, say so and name the
   nearest section. Do not opine beyond the text.

## Output

Short, in prose, in the spec's voice. Cite sections by title, as
`Section title, Subsection`, never by number, and lenses as `LENS-ID`.
Do not restate the spec at length; quote the sentence that decides,
give its reason, then stop.
