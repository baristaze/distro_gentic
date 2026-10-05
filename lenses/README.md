# Lenses

A lens holds the checkable detail under one rule of
[`distro_gentic_spec.md`](../distro_gentic_spec.md), cited here as *the
spec*: the exact field, call, or breach a reviewer looks for in code. It
is stricter than the spec on purpose, and never contrary to it. It never
adds a rule the spec does not state. A review loads one group of lenses
at a time, which keeps it narrow enough to be thorough.

The lenses hold the platform's rules only. Where the spec leans on a
rule of the engine or of the guideline, their own lenses hold it
([the engine's][e-lenses], [the guideline's][g-lenses]), and a lens here
names that rule without restating it.

## Groups

| Group id     | Prefix | File            | Covers |
|--------------|--------|-----------------|--------|
| `placement`  | `PLC`  | `placement.md`  | Sessions Are Work; Session Runners; Placement and Workspace Hosts |
| `workspaces` | `WSP`  | `workspaces.md` | Workspaces and Isolation |
| `watch`      | `WAT`  | `watch.md`      | Watching and Steering |
| `intake`     | `INT`  | `intake.md`     | Work In, Results Out |
| `evidence`   | `EVD`  | `evidence.md`   | Evidence |
| `wall`       | `WAL`  | `wall.md`       | Trust; Data, Retention, and the Wall |
| `money`      | `MNY`  | `money.md`      | Money; Models Are a Fleet Decision |
| `fleet`      | `FLT`  | `fleet.md`      | The Agents a Platform Ships; Failure at Fleet Scale; Operations |

The groups are the ones the spec plans in The Repository.

A rule belongs to one group, and to one lens in it. The `Covers` column
names each group's home sections. Where two groups touch one section,
the paragraph at the top of each file draws the line. A lens may cite a
section outside its group's home when its rule rests there: What Closes
a Loop is cited by the lens of each promise it lists, At a Glance by the
lens of the connections that cross a customer's wall, and Deviations
from the Guideline by the lens of the rule it bends. Where two lenses
meet one breach, the one a reviewer reaches first names the other in
parentheses, and the lens it names carries the severity.

## Lens format

The format is the guideline's, with the spec in place of
`architecture.md`:

```markdown
## PLC-01 Title of the lens

**Principle.** The rule, in a few short sentences, in the spec's voice.

**Source.** Placement and Workspace Hosts, Workspace Hosts (Probing).

**Look for.** What to inspect: files, signatures, declarations, call sites.

**Violation.** What evidence of a breach looks like, concretely.

**Severity.** high | medium | low

**Shape.** `scaffold/acme_root/<path>`

**Check.** review
```

Ids are the group prefix and two digits: `PLC`, `WSP`, `WAT`, `INT`,
`EVD`, `WAL`, `MNY`, `FLT`.

- **Principle** is at most 120 words. A rule that needs more is two
  lenses.
- **Source** names the section and, after a comma, the subsection, by
  title as the spec spells them, never by number. Several citations are
  separated by `;`, and a bare subsection after a `;` belongs to the
  section cited before it. A title may hold commas of its own, as
  `Work In, Results Out` does. A subsection's citation may end in the
  bold labels of the paragraphs it means, in parentheses:
  `Placement and Workspace Hosts, Workspace Hosts (Probing)`.
- **Look for** and **Violation** are one to three sentences each,
  concrete enough that two reviewers flag the same line.
- **Severity** is `high` for a breach of an invariant the spec's The
  Core states, or for a breach the engine grades `high`:
  - a loop left open: a promise of What Closes a Loop the platform does
    not enforce, such as a success without validation at the version
    delivered, or feedback that does not return to its session;
  - a brain run outside the platform's cloud, or inside a sandbox it
    drives;
  - a call into a customer's wall, or a host that advertises what it did
    not probe;
  - an overclaimed or weakened isolation;
  - an execution without its version and provenance;
  - identities confused;
  - a secret resolved anywhere but where it is used, or a cloud secret
    across the wall;
  - spend outside one ledger and one price source, or when no one can
    tell who pays;
  - what the engine grades `high`, done by a platform part: spending
    outside the gate, writing past a lost claim, repeating an unsafe
    call, letting text grant power or an agent hold authority, letting a
    marked session write outward without a person, or switching a model
    silently.

  `medium` bends a shape the spec relies on, and `low` is a convention.
  A lens that cites only `style` sections is `low`.
- **Shape** is optional. It names one or two files or folders of the
  scaffold, `scaffold/acme_root/<path>` in backticks, that show the rule
  as code. A review reads the file and compares the code with it. A lens
  has one only where a scaffold file shows its rule plainly.
- **Check** reads `review` when the review alone judges the lens. The
  platform's checker is named `distro-check`, and its rules go under
  `scaffold/acme_root/checkers/src/acme/distro_check/rules/`, beside
  the engine's checker. A lens it decides says so in the guideline's two
  sentences: "`distro-check` decides it." when it decides the whole
  lens, and "`distro-check` decides `<the part>`; the rest is judged."
  when the review judges what it leaves.

`make lenses` holds the format, a width of 80 columns, the citations,
each Shape path, the Check line against the rules `distro-check`
registers, and every identifier a lens quotes to the section it cites.
That a lens stays inside its rule, stricter and never contrary, is held
by review, not by a program.

[e-lenses]: https://github.com/baristaze/agentic_core/blob/v0.6.1/lenses/README.md
[g-lenses]: https://github.com/baristaze/swe_guidelines/blob/v0.51.1/lenses/README.md
