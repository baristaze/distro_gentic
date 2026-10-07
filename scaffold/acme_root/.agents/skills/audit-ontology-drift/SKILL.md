---
name: audit-ontology-drift
description: "Audit, from the product's checkout, which concepts sit in a layer their nature contradicts. The product is an instance of the platform, which adopts the engine, which follows the guideline. The audit reads each layer at the release the product's base holds, down the scaffold branches' renders, and asks of each namespace, table, agent kind, ADR, skill, lens, checker, and section of a spec or a README whether its layer is the one it belongs to, in either direction: a lower layer's concept grown again above it, or a higher layer's noun sunk below. Then a report: each drift, where it is, where it belongs, and why, with proposed tickets. The gates hold the layers consistent; this asks whether each concept is in the right one. Never changes anything."
allowed-tools: Read, Grep, Glob, Write, Bash(git:*), Bash(mkdir:*)
---

# audit-ontology-drift

Every layer's gates can pass while a concept sits in the wrong layer.
The gates hold the layers consistent with each other: what a layer
states, its code keeps. They cannot say whether a concept belongs to
the layer that holds it. That is an ontology question, and this audit
asks it from the product, the one checkout where every layer is in
view.

## The chain

The product, this tree, is an instance of the platform. The platform
adopts the engine, and the engine follows the guideline. Each layer
takes the scaffold of the one beneath it whole, as the base on its
`scaffold` branch, and adds only what that layer does not hold. From
the bottom:

| Layer | Title | Repository | Spec | ADRs |
|---|---|---|---|---|
| guideline | Software Design and Architecture Guidelines | `https://github.com/baristaze/swe_guidelines` | `architecture.md` | 0001 to 0999 |
| engine | An Engine for Long-Running Agents | `https://github.com/baristaze/agentic_core` | `agentic_core_spec.md` | 1001 to 1999 |
| platform | A Spec for a Closed-loop, Cloud-first, Distributed Agentic Platform | `https://github.com/baristaze/distro_gentic` | `distro_gentic_spec.md` | 2001 to 2999 |
| product | its own spec's title, read in step 2 | this checkout | step 2 | 3001 and up |

The nature of each layer, which the audit holds every concept to:

- **The guideline**: general software design for a multi-tenant,
  service-based system: the object model, interfaces, context, storage
  and its roles, the work queue and workers, the gateway, realtime,
  twins, deployment, and operations. It knows no agent and no model.
- **The engine**: one agent's loop, made durable, bounded, steerable,
  private, and auditable: steps, sessions, context, models, tools,
  policy, streams, steering, identity, agent kinds, budgets, parking,
  and privacy. It knows no fleet and no product's domain.
- **The platform**: a fleet of agents for many tenants, unattended, on
  machines it does not always own, with the loop closed: runners,
  placement, workspace hosts and workspaces, watching and steering,
  intake and feedback, evidence, trust, money, and models as a fleet
  decision. It is domain-free: it holds no product's nouns.
- **The product**: its domain: its nouns, its kinds of work, its
  screens, its integrations, and its choices on top of the platform's
  mechanisms: prices, plans, limits, and default values.

Each layer's spec, at the commit the chain names, opens by saying what
the layer is. Where it says more than the line above, the spec holds,
and the report quotes it.

A concept drifts in one of two directions:

- **Down**: a layer holds a concept that a layer beneath it holds, or
  should: a mechanism every instance of the lower layer would need,
  whatever its domain. An engine concept in the platform or the
  product, a platform concept grown again in the product, a guideline
  concept rebuilt in any layer above it.
- **Up**: a layer holds a concept only a layer above it should know. A
  product's noun in the platform, the engine, or the guideline; a
  fleet's concept in the engine; an agent's concept in the guideline.

These are not drift:

- A layer's choice on top of a lower layer's mechanism: a price, a
  plan, a limit, a default value, or a substitution an ADR records.
- A lower layer's concept that a layer above uses, configures, or
  extends without defining it again.
- A noun in a spec's *Example* line, which illustrates and never adds a
  rule, and a spec's closing Next section, which names what is built on
  it.
- What the product's tree carries unchanged from a lower layer: it is
  judged once, as that layer's, at that layer's path.
- A noun in a migration on a layer's main branch, which never changes:
  a table one migration made and a later one dropped is history.

## Input

None. The audit reads this checkout at its `HEAD`.

## Role and credential

None, no role and no credential. The audit reads this checkout with
`git`, and clones each layer's public repository over HTTPS into the
report's folder. It holds no cloud credential, reads no environment and
no env file, and calls no API but git's.

## Procedure

1. Run `git status --porcelain` here and keep what it prints; step 9
   compares. Make the report's folder,
   `~/Downloads/acme_ontology_drift_<yyyy-mm-dd>/` (`mkdir -p`). It
   holds the layers' clones and, at most, one list of additions for
   each layer (`<layer>-additions.txt`, the list step 5 makes).
   Nothing goes in this checkout.
2. Read the product's title: the first heading of its own spec, the
   document `README.md` or `specs/README.md` names as the product's
   specification. When neither names one, it is the first heading of
   `README.md`. `specs/architecture.md` is the pin to the guideline,
   never the product's spec. The report names the file the title came
   from. Read the product's commit (`git rev-parse HEAD`) and its tag
   (`git describe --tags --exact-match HEAD`; "untagged" when it has
   none).
3. Find the product's base: the render its `HEAD` holds, the newest
   commit it reaches that carries a `Scaffold-Commit` trailer. Each
   commit on a `scaffold` branch is one render, and the main branch
   merges it, so the render is found from `HEAD` alone:

   ```bash
   git log -1 --format=%H --grep='^Scaffold-Commit: ' HEAD
   git log -1 --format='%s%n%(trailers:key=Scaffold-Source,valueonly)%(trailers:key=Scaffold-Commit,valueonly)%(trailers:key=Scaffold-Name,valueonly)' <render>
   ```

   The subject names the platform's release ("The scaffold at v0.7.0
   (…)"); the trailers name its repository, its commit, and the name it
   was rendered under. When the first command prints nothing, the base
   is not recorded: stop, and write a report that says so.
   `distro-upgrade-scaffold` records a base.
4. Read the chain down, one layer at a time, at most three layers below
   the product. For each render's `Scaffold-Source` and
   `Scaffold-Commit`, clone the source once, as the last part of its
   URL, and stand the clone at the commit:

   ```bash
   git clone --quiet <Scaffold-Source> ~/Downloads/acme_ontology_drift_<yyyy-mm-dd>/<repository>
   git -C ~/Downloads/acme_ontology_drift_<yyyy-mm-dd>/<repository> switch --quiet --detach <Scaffold-Commit>
   git -C ~/Downloads/acme_ontology_drift_<yyyy-mm-dd>/<repository> describe --tags --exact-match <Scaffold-Commit>
   git -C ~/Downloads/acme_ontology_drift_<yyyy-mm-dd>/<repository> log -1 --format=%H --grep='^Scaffold-Commit: ' <Scaffold-Commit>
   ```

   A clone left by an earlier run that day is fetched
   (`git -C <clone> fetch --quiet --tags origin`), never cloned again.
   The release is the tag `describe` prints; with none, the one the
   render's subject names; with neither, "untagged" and the commit.
   The last command finds the layer's own base, the render its commit
   holds: read that render's subject and trailers as in step 3, for the
   next layer down. A layer whose commit holds no render is the root,
   the guideline, and the chain ends there. A source the chain's table
   does not name is read the same way and reported as an unknown layer.
   A fourth layer below the product is never read; the report names it.
   A clone that fails is reported as not read, with git's line, and the
   chain ends there.
5. List what each layer adds. A layer's own concepts are the files it
   added over its base, and a changed file is its change to a lower
   layer's concept:
   - The product: `git diff --name-status --find-renames <render> HEAD`
     here.
   - A layer with a base:
     `git -C <clone> diff --name-status --find-renames <render> <Scaffold-Commit> -- scaffold/`,
     where `<render>` is the render step 4 found in that clone.
     Beside it, the texts that never reach a product: the headings of
     its spec, its `lenses/`, its `skills/`, and its `agents/`.
   - The root: its whole `scaffold/` folder and the same texts.

   A layer's scaffold is the one folder under its `scaffold/` whose
   name ends in `_root`, and the word before `_root` is the placeholder
   name its paths carry. This tree's paths carry the product's name,
   the `Scaffold-Name` of step 3.
6. Group each layer's additions into concepts, by kind: a namespace
   (`om/src/<name>/om/<namespace>/`), a table (a migration under
   `om/migrations/`), an agent kind, an ADR (`docs/adr/`, its title is
   its decision), a skill (`.agents/skills/<name>/`, its description),
   a checker (`checkers/`) or a lens, an app, a service, a worker, or
   an integration, and a section of a spec or a README (its heading). A
   concept is judged once, at the layer that added it. An ADR whose
   number lies in another layer's range than the layer that added it is
   a sign worth reading.
7. Ask the question of each concept: does the layer it lives in
   contradict its nature, as The chain states it? Judge by its name and
   its one-line purpose first. Two searches find what a reading alone
   misses, each over a clone at the chain's commit, whole words in any
   case, a noun's forms in one search:
   `git -C <clone> grep -n -w -i -e <noun> -e <its plural>`.
   - Up: each noun the product added (its namespaces, its kinds of
     work, its agent kinds, its spec's terms) is searched in every
     layer below it, and each of the platform's own nouns in the engine
     and the guideline. A hit outside an *Example* line and a Next
     section is a higher layer's noun below it.
   - Down: each concept a layer added is searched by its noun in the
     layers beneath it. A lower layer that holds the same mechanism
     means the upper one grew it again, unless it is a choice on top.

   Search at most 40 nouns, a noun and its plural one, each once in
   each layer below it. Read a suspect in full before it is reported:
   at most 30 files read in full in a run. A suspect past either count
   is listed under Not verified.
8. Write the report, `~/Downloads/acme_ontology_drift_<yyyy-mm-dd>.md`.
   Each drift names the concept and its kind, where it is (the layer
   and the path at its commit), where it belongs (the layer), the
   direction, and why: the nature it contradicts, with the evidence, a
   line or a search hit. Each drift carries a proposed ticket, in the
   repository where the move happens: a move down is a ticket in the
   lower layer's repository to hold it, and one in this checkout to
   take it from there; a move up is a ticket in the lower layer's
   repository to take the noun out. The audit proposes; it never fixes.
9. Run `git status --porcelain` here again. It prints what step 1
   printed. When it does not, the report's Not verified names each path
   that changed, and the person decides; the audit undoes nothing.

## What it never does

- Never writes to a shared database or to an environment: it reads
  git and the layers' public repositories, and writes its clones and
  its report under `~/Downloads/`.
- Never modifies a tracked file, never commits, never opens a pull
  request. In this checkout it runs only the git commands that read:
  `status`, `rev-parse`, `log`, `diff`, and `describe`. It never
  fetches, switches, or checks out here.
- Never files a ticket, and never pushes to or opens anything on a
  layer's repository: a proposed ticket is the person's to file.
- Never reads more than three layers below the product, searches more
  than 40 nouns, or reads more than 30 files in full.

## Output

`~/Downloads/acme_ontology_drift_<yyyy-mm-dd>.md`:

```markdown
# Ontology drift: <the product's title>, at <commit>

**Answer.** <one sentence: how many drifts, which way, and the worst>

## The chain

| Layer | Title | Repository | Release | Commit | Its base |
|---|---|---|---|---|---|
| product | <title> (`<file>`) | this checkout | <tag or untagged> | <commit> | <render>, the platform at <release> |
| platform | A Spec for a Closed-loop, Cloud-first, Distributed Agentic Platform | distro_gentic | <release> | <commit> | <render>, the engine at <release> |
| engine | An Engine for Long-Running Agents | agentic_core | <release> | <commit> | <render>, the guideline at <release> |
| guideline | Software Design and Architecture Guidelines | swe_guidelines | <release> | <commit> | none: the root |

## Drifts, by impact

1. **<concept>** (<kind>), <down or up>. Where it is: <layer>,
   `<path>`. Where it belongs: <layer>. Why: <the nature it
   contradicts>; evidence: <the line or the search hit>.

## Proposed tickets

- <repository>: <title>: <what, why, done-when>

## Considered, not drift

- <concept>: <why its layer fits it>

## Not verified

- <a layer not read, a suspect past a count, a path that changed>
```
