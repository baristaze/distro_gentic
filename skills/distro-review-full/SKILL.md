---
name: distro-review-full
description: "Full platform review: the nine lens groups of the distro_gentic spec run in parallel beside the engine's and the guideline's full reviews, and the three layers merge into one report. Use before a pull request to platform code, or when a change crosses groups."
allowed-tools: Read, Grep, Glob, Agent, Skill, Bash(git diff:*), Bash(git show:*), Bash(git log:*), Bash(git status:*), Bash(git rev-parse:*), Bash(git merge-base:*), Bash(git symbolic-ref:*), Bash(git ls-files:*)
---

# distro-review-full

A platform stands on two layers, and its full review judges all three,
each once. This skill runs the platform's nine lens groups over one
scope, in parallel, each by its own reviewer so that no perspective is
diluted by another. The layers beneath have full reviews of their own,
and those are theirs to run: the engine's `agentic-review-full`, from
the engine's plugin, judges the engine's rules, and the guideline's
`arch-review-full`, from the guideline's plugin, judges the guideline's.
This skill starts both beside its own groups, with the same arguments,
and never runs a lens of theirs itself. It fans out, collects, and
merges the three layers' reports into one.

## Input

The arguments name what to review, exactly as `distro-review-<group>`
reads them (see `../distro-review-placement/SKILL.md`, Input; a path
that starts with `../` is read from this skill's folder as `realpath`
resolves it). Resolve the scope once, here, into a concrete
description (the list of files, or the range or commit) and hand the
same description to every reviewer of this layer so the nine reports
cover the same ground. A range or a commit is handed over as the ref,
with its list of files, and the reviewer reads each file at the
range's end or the commit, never from the working tree. `all` and a
path or a glob, which can be large, are handed over as the path or the
glob (`.` for `all`), the commit `HEAD` is at, and the count of files
the `git ls-files` call gave, never as a list: each reviewer lists them
itself with the same call, and reads the working tree, never that
commit, which only records where `HEAD` stood. The layers beneath get
the arguments as given, and resolve them by the same rules. An empty
scope is reported as "nothing to review" and the skill stops. `all`
costs nine full reads of the repository for this layer, and the layers
beneath add their own; a path or a range is the cheaper question
whenever the change is narrower than the tree.

## Procedure

1. Resolve the scope and write it down in one line.
2. Take this skill's folder from the base directory the host names when
   it loads the skill, and make the paths from it absolute: the lens
   catalog is `../../lenses/` and the spec is
   `../../distro_gentic_spec.md`. Run no command to find the folder:
   `realpath` is not pre-approved, so an unattended run would stop on a
   prompt. Reviewers do not see this skill's text, so pass them
   absolute paths.
3. Load the two full reviews beneath, each as the host loads a skill by
   name, with the arguments as given: the engine's `agentic-review-full`
   (`/agentic-core:agentic-review-full` in Claude Code) and the
   guideline's `arch-review-full` (`/swe-guidelines:arch-review-full`).
   Follow each one's procedure as it is written, up to the launch of its
   reviewers. A layer whose skill the host does not list is not run:
   the report says so, and names the plugin that holds it. This skill
   never judges a lens of that layer in its place.
4. Where the agent can start subagents, launch every reviewer of the
   three layers at once: those each skill beneath launches, as it says,
   and this layer's nine, one per group. Each of the nine gets the
   scope line, the group name, the absolute path of its lens file
   (`<catalog>/<group>.md`), and the absolute path of the spec. Use the
   `distro-reviewer` agent that `../../agents/distro-reviewer.md`
   defines for Claude Code (`distro-gentic:distro-reviewer` when
   installed as the plugin). When no such agent is installed, give a
   general subagent the scope line (it stands for the skill's
   arguments), the group name, the absolute paths of the lens file and
   the spec, and the text of `../distro-review-<group>/SKILL.md` with
   every path in it that starts with `../` made absolute from that
   skill's folder, which sits beside this skill's folder, first, since
   the subagent reads it from elsewhere. Tell it that the run is
   read-only (it never edits, stages, or commits, and never runs a file
   of the repository under review), and that it returns its report
   within 80 turns, the cap `distro-reviewer` holds. Where the agent
   has no subagents, run the nine group procedures one after another in
   this session, and each layer beneath as its skill says. The groups:
   - `distro-review-placement`
   - `distro-review-workspaces`
   - `distro-review-stations`
   - `distro-review-watch`
   - `distro-review-intake`
   - `distro-review-evidence`
   - `distro-review-wall`
   - `distro-review-money`
   - `distro-review-fleet`
5. Wait for every reviewer. A report of this layer follows the group
   format when every section of it is there (the title, the Scope and
   Lenses lines, Findings, Deviations, Passed, Unverified, Not
   applicable) and its counts add up: applied is passed plus findings
   plus unverified, and applied plus not applicable is the number of
   `## <LENS-ID>` headings in its lens file. A reviewer that fails (an
   error, or no report within its turns), or returns a report that does
   not follow the group format, is re-run once with the same message,
   as soon as it returns; if it fails again, its group is reported as
   "not reviewed" with the error. Each layer beneath checks, re-runs,
   and merges its own reviewers' reports as its skill says, into the
   report that skill would write. That report is kept for step 7 and
   never written out on its own. A layer beneath whose run fails is
   reported as not run, with the error.
6. Merge this layer's nine reports:
   - First write every path repository-relative, as `git ls-files`
     prints it at the root: no leading `./`, no absolute prefix, no
     `<ref>:`. The matching and sorting below compare these.
   - Concatenate all findings and sort by severity (high, medium, low),
     then by file and line.
   - When two findings, from two groups or one, flag the same
     `path:line`, keep both lens ids on one line; the fix text comes
     from the higher-severity one. At equal severity the group whose
     opening paragraphs (the top of its lens file) own the rule wins the
     fix text, and the other id stays on the line. Within one group at
     equal severity, the lower lens id wins, and between two lines of
     one lens, the first by file and line. Each id stays on the line
     once, the winner's first.
   - Two findings whose fixes change the same symbol (the class,
     method, or setting the Fix sentence edits, never one it only
     names) merge into one line the same way, whatever their
     `path:line`; the line named is the winner's.
   - Concatenate every group's Deviations lines, in lens id order.
   - Count applied, passed, findings, unverified, and not-applicable
     lenses across groups. Applied is passed plus findings plus
     unverified; applied plus not applicable is the size of the
     catalog, so every lens is counted once.
7. Merge the three layers. A report from beneath is taken as its skill
   wrote it: no finding of it is judged again, graded again, or
   dropped here, and no lens of it appears twice.
   - Write its paths repository-relative too, then concatenate the
     findings of the three layers and sort them as step 6 does.
   - When findings of two layers flag the same `path:line`, keep their
     lens ids on one line; the fix text comes from the higher-severity
     one. At equal severity the lower layer's wins (the guideline's over
     the engine's, the engine's over the platform's), since a rule
     leans on the rules beneath it and never restates them. The
     winner's ids come first. Findings of two layers merge on the same
     `path:line` alone, never on a shared symbol.
   - Deviations: the platform's lines, then the engine's, then the
     guideline's, or `None.` when there are none. They are not findings
     and count nowhere.
   - Counts: each layer's Lenses line gives its row in By layer, and
     the Lenses line adds the layers that ran.
   - Passed, Unverified, and Not applicable: the platform's ids, then
     the engine's, then the guideline's, each in id order.
8. Write the merged report below. Then, if the report has three or
   more `high` findings, say so in one sentence after the report,
   with the count. Nothing else.

Never edit, stage, or commit, and never run a file of the repository
under review. This skill reads and reports; what a skill beneath runs
is that skill's to say.

## Output

The group report shape, plus a `Layers` line, a `Groups` line, a
per-layer table, and a per-group table of this layer:

```markdown
# Platform review

**Scope.** <the scope line>
**Layers.** platform, engine, guideline (a layer not run: `<layer> (not run: <why>)`)
**Groups.** placement, workspaces, stations, watch, intake, evidence, wall, money, fleet
**Lenses.** <n> applied, <p> passed, <f> findings, <u> unverified, <x> not applicable

## Findings

- **<LENS-ID>[, <LENS-ID>] <severity>** `<path>:<line>` <what breaks the rule>. Fix: <one sentence>.

## Deviations

- **<LENS-ID>** `<path>:<line>` ADR-NNNN <what the ADR accepts, a few words>.

## By layer

| Layer     | Review                | Applied | Passed | Findings | Unverified | Not applicable |
|-----------|-----------------------|---------|--------|----------|------------|----------------|
| platform  | `distro-review-full`  |         |        |          |            |                |
| engine    | `agentic-review-full` |         |        |          |            |                |
| guideline | `arch-review-full`    |         |        |          |            |                |

## By group

| Group      | Applied | Passed | Findings | Unverified | Not applicable |
|------------|---------|--------|----------|------------|----------------|
| placement  |         |        |          |            |                |
| workspaces |         |        |          |            |                |
| stations   |         |        |          |            |                |
| watch      |         |        |          |            |                |
| intake     |         |        |          |            |                |
| evidence   |         |        |          |            |                |
| wall       |         |        |          |            |                |
| money      |         |        |          |            |                |
| fleet      |         |        |          |            |                |

## Passed

<LENS-ID>, <LENS-ID> (`<path>`), ... (the platform's, the engine's, then the guideline's, each in id order; a `high` lens names the file that proved it)

## Unverified

<LENS-ID> (<what would decide it>), ...

## Not applicable

<LENS-ID> (<why>), ...
```

A layer not run fills its By layer row with `not run`. The By group
table covers this layer alone; each layer beneath counts its own groups
in its own report, and this one keeps only its row.
