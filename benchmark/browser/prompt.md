# The prompt

`distro-benchmark-browser` sends this prompt to four chat products, in
one message each. It names the repository's public URL, and the whole
repository is judged; nothing is attached. It is the engine's prompt,
[`benchmark/browser/prompt.md`](https://github.com/baristaze/agentic_core/blob/main/benchmark/browser/prompt.md)
in `agentic_core`, wherever the platform does not differ from the
engine. It differs in the role, the subject and its URL, the category,
the adjacents, and the rubric's areas. Its report format has the
engine's sections in the engine's order, so the two read side by side.

The block's last section, from `## Report format` to its end, is the
contract: the shape every answer takes, so the four answers line up.
A run records the prompt and the contract as it typed them, and two
runs compare only when both texts are the same.

```text
You are a highly senior software engineer and software architect specializing in distributed agent platforms and the infrastructure that runs fleets of agents.

Evaluate the `distro_gentic` repository at https://github.com/baristaze/distro_gentic strictly on its software design and architecture merits. Judge the whole repository, not one file of it.

Your goal is not merely to review `distro_gentic` in isolation. Your goal is to determine:

1. What architectural problem it is actually solving.
2. How good its design is for that problem.
3. Which existing systems are its closest architectural adjacents.
4. Where `distro_gentic` is concretely stronger, weaker, broader, narrower, or simply different.
5. How all compared systems score under one consistent architectural rubric.

Evaluate the material itself. Do not be biased by who wrote it, an agent or a human, by how fast it was written, or by how new it is.

## Evaluation process

Follow this order deliberately. Do not skip ahead.

### 1. Understand and classify `distro_gentic`

First, read the repository in full, starting with its specification, `distro_gentic_spec.md`.

Determine:

- What problem `distro_gentic` is trying to solve.
- Its intended abstraction level.
- Its architectural role inside an application.
- Its core execution model.
- Its primary abstractions.
- Its intended extension points.
- What it owns.
- What it deliberately delegates elsewhere.
- What it is.
- Equally importantly, what it is not.

`distro_gentic` builds on an engine, `agentic_core`, which runs one agent's loop, and on general software design guidelines, and it cites both rather than repeat them. It is a platform that runs fleets of agents in a closed loop on that engine: placement, trust, money, workspaces and hosts, intake, evidence, and watching. Judge it as that, not as one agent's loop.

Do not force it into the category of "agent framework" or "agent orchestrator" if a more precise category describes it better. Name the category you would file it under, in a few words, and say why that name fits better than the obvious ones.

Then identify the closest existing architectural adjacents.

Potential examples include:

- hosted autonomous coding-agent platforms, which take work in and run agents unattended on machines they provide
- agent orchestration on a durable-execution engine, where the overlap is durability and scheduling rather than the agent loop
- CI-driven agent runners, which start an agent from an event in a repository or a tracker and hand its result back
- other systems that are more directly comparable to what `distro_gentic` actually provides

These examples are suggestions, not mandatory choices. Name the specific systems yourself.

Select the **2 to 3 most relevant adjacents based on architectural overlap**, not popularity.

For each selected adjacent, briefly explain why it is a relevant comparison and what portion of `distro_gentic` it overlaps with.

### 2. Define and freeze the scoring rubric

Before scoring anything, define a common architectural evaluation rubric.

The rubric should fit the category you identified in step 1.

Potential areas include:

- conceptual model and abstraction quality
- separation of concerns between the platform, the engine beneath it, and a product built on it
- composability and extensibility for a product built on it
- placement and scheduling of sessions across runners and hosts
- workspace isolation and multi-tenancy
- trust boundaries, identity, and the wall around a tenant's data
- cost, budgets, and metering across a fleet
- intake of work from outside, and results going back
- evidence and auditability of what agents did
- watching and steering live sessions
- failure semantics at fleet scale: leases, retries, and recovery
- determinism, replayability, and testability
- observability and operations
- type safety and contract clarity
- operational complexity
- developer ergonomics
- architectural coherence and simplicity

Modify, combine, remove, or add criteria where appropriate after understanding the actual design.

Avoid excessive fragmentation. Prefer approximately **8 to 12 meaningful architectural criteria** rather than a long checklist of overlapping concerns.

For each criterion:

1. Give it a concise name.
2. Define exactly what it measures.
3. Describe what a `10/10` architecture would look like.
4. Assign a weight.
5. Ensure all weights sum to exactly **100**.

Once defined, **freeze the rubric**.

Do not change criteria, definitions, weights, or scoring interpretation after you start scoring `distro_gentic` or its adjacents.

### 3. Evaluate `distro_gentic`

Score `distro_gentic` against every frozen criterion on a **0 to 10 scale**.

Use the scale consistently:

- `0-2`: fundamentally absent, broken, or architecturally unsuitable
- `3-4`: significant weaknesses or major missing pieces
- `5-6`: reasonable but materially incomplete or compromised
- `7-8`: strong architecture with identifiable limitations
- `9`: excellent, unusually strong design
- `10`: exceptional and difficult to improve materially for the intended scope

Do not treat `10` as merely "supports the feature."

For every score:

- Ground the assessment in concrete design decisions from the repository, and name the file and the section they come from.
- Distinguish specified architecture from aspirational language.
- Identify important ambiguities and underspecified behavior.
- Do not award points for functionality that is merely implied.
- Do not penalize intentional narrowness when it improves coherence.
- Do not penalize the project simply because it is new.

Calculate the weighted result: the sum of each score times its weight, divided by 10, rounded to a whole number.

### 4. Evaluate the selected adjacents

Apply the **exact same frozen rubric** to every selected adjacent.

Use their current architecture and primary documentation or source repositories where possible. Name the version or the date of what you read.

Evaluate architectural properties, not ecosystem momentum.

Do **not** use any of the following as scoring criteria:

- age of the project
- GitHub stars
- follower count
- community size
- market share
- production adoption
- company backing
- version number
- number of integrations, where that number comes from ecosystem size rather than from the design

Where an adjacent's architecture is not documented well enough to score a criterion, say so, score only what is documented, and mark that score as low confidence. Never fill a gap with what the system probably does.

Compare like with like. Where an adjacent covers less than `distro_gentic` (or more), score each criterion on what each system specifies for it, and say in a line that the scopes differ. Do not reward or penalize scope that the criterion does not measure.

Calculate each adjacent's weighted result the same way.

### 5. Compare

Put every system side by side under the frozen rubric.

Then say, concretely, where `distro_gentic` is:

- stronger: a design decision an adjacent lacks, and what it buys;
- weaker: a decision an adjacent makes better, and what it costs `distro_gentic`;
- broader or narrower: what one owns that the other leaves to the application;
- simply different: a trade-off where neither side is better, and when each choice wins.

Each point names the design decision behind it, not a feature list.

### 6. Recommend

Name the changes to the repository that would raise its score most, most valuable first. Each names the criterion it moves and roughly by how much. Prefer a change that removes or clarifies over one that adds.

## Report format

Answer in this shape, so evaluations compare:

- First line: `Score: NN/100`, the weighted score of `distro_gentic`, and nothing else on that line.
- `## Classification`: what it is, its abstraction level, what it owns, what it delegates, and what it is not, one line each; then the category you would file it under, in a few words.
- `## Adjacents`: each selected system, why it was chosen, and the part of `distro_gentic` it overlaps, one line each.
- `## Rubric`: a table of each criterion, what it measures, what a `10/10` looks like, and its weight; the weights sum to 100.
- `## Scores`: a table with one row per criterion (its weight, then each system's score) and a last row of each system's weighted result out of 100.
- `## distro_gentic, criterion by criterion`: for each criterion, its score and its grounding in the repository, with the ambiguities that held it back, a short paragraph each.
- `## Where it differs`: stronger, weaker, broader or narrower, and different, one line each.
- `## What I would change`: concrete edits to the repository, most valuable first, one line each.
- `## Method`: what you read (the repository's files, and the commit or tag they stood at; each adjacent's documentation or source with its version or date), how deep, and which scores rest on thin evidence, one line each.
```
