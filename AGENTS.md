# Working in this repository

This repository holds one spec (`distro_gentic_spec.md`), the parts that
make its rules checkable and runnable (`lenses/`, `skills/`, `agents/`,
`scaffold/`), and the scripts that keep them consistent
(`scripts/`, `Makefile`). It adopts the [Software Design and
Architecture Guidelines](https://github.com/baristaze/swe_guidelines),
*the guideline*, and has its shape. It builds on the engine,
[`agentic_core`](https://github.com/baristaze/agentic_core), and
repeats neither. Each script's docstring states what it holds. Read it
before you change what it checks.

## The ladder

The spec tells the story and states every rule the platform adds. The
guideline states every rule of general software design, and the engine
every rule of one agent's loop; the spec cites them rather than repeat
them. A lens or a skill holds the checkable detail under a rule the
spec states. It is stricter than the story on purpose, never contrary
to it, and it never adds a rule the spec does not state. The gates are
stricter still. When the spec changes, every lens and skill that cites
the changed text changes with it.

## Writing

- A person and an agent read the spec, the READMEs, and `docs/`. They
  tell the story and point at the detail: short sentences, one idea
  each, in the present tense, with no history.
- Only agents read the lenses, the skills, and `agents/`. They may be
  exact, and they name the scaffold file whose shape to follow.
- Detail goes where it is held: code to the scaffold, checkable detail
  to a lens, steps and edge cases to a skill, a stance and its reasons
  to an ADR. What only an agent needs on a person's page goes in a
  short agents-only block, opened by `<!-- agents-only` alone on its
  line; nothing inside may close it. Tags follow How to Read This, in
  the spec.
- The spec borrows a product's nouns in its examples only, to
  illustrate, and stations are its optional section. Nothing else here
  carries product or hardware vocabulary, and nothing outside the spec
  names a repository but the guideline and the engine.

## Layout

- `distro_gentic_spec.md` is the source of truth. Its Contents lists
  every section that follows it; it is generated (`make gen-toc`) and
  checked (`make toc`). Headings are unnumbered, and every
  cross-reference names a section by its title. A rule of the guideline
  is cited by a link pinned at a release, and a rule of the engine by a
  link to its spec on GitHub, its anchor kept.
- `lenses/<group>.md` holds one group of lenses in the guideline's lens
  format. The spec's The Repository names the groups.
- `skills/distro-<name>/SKILL.md` is a skill of this plugin. Its `name`
  is its folder's and starts with `distro-`, so it never collides with
  the guideline's `arch-*` or the engine's `agentic-*`.
  `scripts/check_skills.py` holds its frontmatter and the paths it
  names, and one `distro-review-<group>` skill per row of the group
  table in `lenses/README.md`, each named by `distro-review-full`.
- `agents/distro-<name>.md` is a Claude Code subagent a skill fans out
  to. `scripts/check_agents.py` holds its frontmatter and its
  `maxTurns`, and holds `agents/distro-reviewer.md` to the review
  template's procedure and report.
- `scaffold/acme_root/` is the platform's domain-free core under the
  name `acme`, built on the engine's scaffold. Its ADRs, in
  `scaffold/acme_root/docs/adr/`, are numbered from 2001, so they never
  meet the guideline's (below 1000) or the engine's (1001 to 1999). Its
  skills sit in `.agents/skills/`, and its `.claude/skills` is a link to
  them; `scripts/check_skills.py` holds their frontmatter and the link.
- `.claude-plugin/` holds the plugin and marketplace manifests; the
  repository root is the plugin, `distro-gentic`. `plugin.json` carries
  the one release version, and `scripts/check_version.py` holds every
  copy to it.
- `scripts/_common.py` holds what the scripts share: the heading anchor
  rule, the one list of the repository's Markdown (`markdown_files`),
  the argument parser, and the fence rule (`fenced_lines`).
- `tests/` holds one pytest module per script, with a pass and a fail
  path per rule; `make test` runs them.

A gate over a folder that does not exist passes on the empty set, so
each part is held from the change that adds it.

## Invariants

- Every skill follows the [Agent Skills
  standard](https://agentskills.io/specification), so it runs in any
  agent that reads it. Its frontmatter holds the standard's fields and
  nothing else, except `disable-model-invocation`: Claude Code's key,
  which the standard's validator refuses. So only a skill a person must
  start by name carries it, and that skill also carries Codex's switch,
  `agents/openai.yaml` with `policy.allow_implicit_invocation: false`.
- A skill names its own files by a path from its own folder
  (`../../distro_gentic_spec.md`, `references/<file>`), never through a
  path one agent substitutes, such as `${CLAUDE_SKILL_DIR}`. A skill
  that climbs out of its folder says the path is read from the folder
  as `realpath` resolves it. Its arguments are "the arguments", never
  `$ARGUMENTS`.
- A skill's `allowed-tools` names only what its body runs.
  `scripts/check_skills.py` holds the frontmatter, the make targets, and
  the paths; the git, uv, and pnpm entries are held by hand.
- "X, never Y" names the near miss a rule rules out. It is part of the
  rule, not history.

## Validate

```bash
make check                          # the root gates
claude plugin validate . --strict   # the manifests (when claude is installed)
```

`.github/pins/` holds every tool version the Makefile and CI run.

## Conventions

- Prose wraps at about 72 columns. A concept the spec uses before the
  section that defines it links that section at its first mention.
- A fix applied to one instance is searched for its siblings, and they
  are fixed in the same change.
- A commit message has a specific subject and a short body naming the
  rule that changed and why.
- A change never edits `CHANGELOG.md`. Its pull request description
  carries what the release needs: what changed, the level
  `CONTRIBUTING.md` (Versioning) gives it, and a reversal named as one.
