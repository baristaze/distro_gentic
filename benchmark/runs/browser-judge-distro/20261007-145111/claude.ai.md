# claude.ai

- URL: [redacted]
- Model: Opus 5.5
- Effort: High
- Sent: 2026-10-07T14:55:54Z
- Finished: 2026-10-07T15:18:01Z (the page's status "Claude finished the response", seen at poll 18)
- Status: ok
- Score: 73/100
- Read: main at 76ed581 (v0.9.0, 2026-10-07)
- Polls: 18
- Note: the new-chat composer held a leftover draft of this prompt, cleared before typing; the composer's permission chip read Manual (Claude asks before using new tools or opening new sites), and no line said the product could act on the machine or named a device, before the send or at any poll; the answer paused on dialogs asking to fetch a web page (pages on docs.temporal.io and arxiv.org), each declined as its most privacy-preserving choice, and the answer says two fetches were refused by the session's permissions; the answer names benchmark/runs/ only to say it did not read the scores there

## Answer

I'll read the distro_gentic repository in full, starting with its spec, then research two or three adjacent systems and score them all under one frozen rubric.

Score: 73/100

## Classification

- **What it is:** a specification for a multi-tenant control plane that runs fleets of agent sessions unattended for days. It ships with checkable lenses and a working scaffold: about 1,040 files added on top of the engine's scaffold.
- **Abstraction level:** a platform and control plane, one layer above the agent loop (`agentic_core`) and one layer below a product (`[redacted]`).
- **Role in an application:** it is the substrate a product is rendered from. The product forks the scaffold under its own name and merges platform releases into it. It is not a library the product calls.
- **Core execution model:** a session lives in the control plane. Progress is a row in one work queue, of kind `loop`, `exec`, `workspace` or a platform or product kind. Runners in the cloud claim loops under a lease and a writer epoch. Workspace hosts, in the cloud or inside a customer's wall, pull `exec` work outward.
- **Primary abstractions:** session, kind of work and its lane, placement and host pool, workspace host with probed modes and owner's ceilings, execution record with provenance, validation policy, the result gate, four identities, the ledger and price table, and the model matrix.
- **Extension points:** product kinds of work, agent kinds, automation actions, integrations with their twins, workspace providers, and results-contract checks. Each has a `distro-scaffold-*` skill.
- **What it owns:** placement, trust and the customer's wall, money, workspaces and hosts, intake and feedback routing, evidence and the result gate, watching and steering, fleet failure, and operations.
- **What it delegates:** the agent loop, steps, policy, budgets-as-gate and parking go to the engine. General design (queue, gateway, storage roles, sweep, twins) goes to `swe_guidelines`. Wire protocols, default values and the threat model go to each deployment (spec, "What This Spec Does Not Cover").
- **What it is not:** an agent framework, a workflow engine, a sandbox provider, or a coding agent. It doesn't define how an agent reasons.
- **Category:** a *closed-loop agent-fleet control plane*. "Orchestrator" suggests routing between agents, which it explicitly refuses (spec, "The Agents a Platform Ships": "There is no router"). "Framework" suggests a library. What it actually provides is a multi-tenant control plane whose distinctive job is to close the loop between work, evidence and feedback.

## Adjacents

- **OpenHands (Software Agent SDK v1.53.0, Agent Canvas v1.25.0, `automation`, docs, all read 2026-10-07).** A hosted and self-hostable autonomous coding-agent platform. It overlaps on runners and agent-server, sandboxed workspaces, live streaming and steering, and intake through resolvers and automations.
- **GitHub Copilot cloud agent, formerly "coding agent" (docs and changelog read 2026-10-07).** The clearest CI-driven agent runner. Work comes in from a tracker and runs on an ephemeral Actions runner, possibly self-hosted. The result goes back as a pull request, and comments iterate on it. It overlaps on intake, feedback return, egress, trust and metering.
- **Temporal with `temporalio-openai-agents` v1.1.0 (SDK 1.34.0).** An agent loop on a durable-execution engine. It overlaps on placement (task queues, pull-based workers, priority and fairness) and on failure semantics: leases, retries and replay.

## Rubric

Frozen before scoring.

| # | Criterion | Measures | 10/10 looks like | Weight |
|---|---|---|---|---|
| 1 | Conceptual model and layering | Abstraction quality; the engine, platform and product split; owned vs delegated | Few orthogonal concepts, each with one owner; layers that cannot leak; each invariant stated once | 12 |
| 2 | Placement and scheduling | Queues, lanes, fairness, pinning, admission | One work model for every kind; placement is data; fairness and tenant limits enforced at claim; deployed as specified | 9 |
| 3 | Workspace isolation and egress | Sandbox strength, tenant separation, egress, lifecycle | Hardware-virtualized isolation per session; probed claims; an enforced egress allowlist; a credential-free environment; no lost work | 11 |
| 4 | Trust, identity and secrets | Identities, authority, untrusted input, secrets, operator access | Distinct identities on every action; the agent holds no authority; text cannot instruct; secrets resolved at use; provable content access | 12 |
| 5 | Failure semantics and durability | Leases, fencing, retries, side-effect idempotency, recovery, outages | Fencing on every write; keyed side effects, never repeated when unsafe; deterministic recovery; fleet-wide outage handling | 12 |
| 6 | Evidence and validation | What counts as a result; independence; protected checks; statistics; audit | Success only through a gate over independently produced, versioned, provenance-tagged evidence; statistically sound; tamper-resistant | 10 |
| 7 | Cost, budgets and metering | Metering, holds, ledger, pricing, fleet model choice | A gate before every call; one ledger and one price source; fails closed; rate and spend kept apart; versioned, qualified model choice | 8 |
| 8 | Intake and feedback return | Work in, results out, feedback to the same session, automation bounds | Signed intake; routing to the same session; explicit wake rules; bounded automations; origin-labelled text | 8 |
| 9 | Watching and steering | Live view, steering, takeover, notification | The live view is a window on the records; steering at defined points; takeover recorded and attributed | 6 |
| 10 | Extensibility and contract clarity | Extension points; versioned wire types; typed contracts | Named, typed, versioned extension points; product kinds registered like platform kinds; compatibility checks | 6 |
| 11 | Operability and testability | Telemetry, runbooks, deterministic tests, replay, operational burden | Bounded telemetry; end-to-end tracing; twins and scripted providers; replay; low burden for what it does | 6 |
| | | | | **100** |

## Scores

| Criterion | Weight | distro_gentic | OpenHands | Copilot cloud agent | Temporal + OpenAI Agents |
|---|---|---|---|---|---|
| 1 Conceptual model and layering | 12 | 8 | 7 | 7 | 8 |
| 2 Placement and scheduling | 9 | 7 | 4 | 5 (low conf.) | 7 (med. conf.) |
| 3 Isolation and egress | 11 | 5 | 5 | 5 (low conf.) | 2 |
| 4 Trust, identity and secrets | 12 | 8 | 4 | 7 | 4 (low conf.) |
| 5 Failure semantics | 12 | 8 | 5 | 3 (low conf.) | 8 |
| 6 Evidence and validation | 10 | 7 | 3 | 5 | 3 |
| 7 Cost, budgets and metering | 8 | 7 | 4 (low conf.) | 6 | 1 |
| 8 Intake and feedback | 8 | 8 | 5 | 6 | 4 (low conf.) |
| 9 Watching and steering | 6 | 8 | 7 | 7 | 5 (low conf.) |
| 10 Extensibility and contracts | 6 | 7 | 8 | 6 | 8 |
| 11 Operability and testability | 6 | 7 | 6 | 6 | 8 |
| **Weighted result** | 100 | **73** | **51** | **56** | **52** |

Scopes differ a lot. Temporal leaves isolation, money, evidence and intake to the application, and Copilot is one repository, one PR and 59 minutes per session. Each score measures only what the system specifies for that criterion.

## distro_gentic, criterion by criterion

**1. Conceptual model and layering — 8.**
- **Strengths:**
  - The four planes (control, brain, hands, records and money) in spec "At a Glance" are crisp.
  - "Sessions Are Work" reduces every kind of work to one queue with one row shape.
  - The spec says only what the platform adds and cites the engine and guideline for the rest.
  - Deviations are recorded by rule id (spec, "Deviations from the Guideline").
  - 106 lenses, each tied to one rule, keep rules checkable.
- **What held it back:**
  - The spec is not self-contained. Reading it properly takes three repositories.
  - The spec's engine links point at `agentic_core/blob/main/...` (spec lines 999–1015), while `lenses/README.md` and the latest commits pin v0.8.0.
  - None of the 106 lenses carries a **Shape** path to the scaffold (`grep '^\*\*Shape' lenses/*.md`), despite 167k added lines. The rule-to-code link exists only in reviewers' heads.

**2. Placement and scheduling — 7.**
- **Implemented as specified:**
  - Kinds and lanes are one registry (`om/placement/kinds.py:281-311`).
  - Each loop goes to the lane of its tier or of its tenant (`placement/rules.py:18-29`).
  - A tenant's limit is a guard at claim that defers and refunds the attempt (`session_runner/.../fair_share.py:28-32`, `work/rules.py:33-35`). Tests assert this.
  - A host's claim is filtered by its credential's identity, never by its request (`hosts/impl/manager.py:424-432`).
  - A version floor is checked at every claim.
- **What held it back:**
  - The deployed runner serves only `loop:standard` (`session_runner/settings.py:39`; Terraform never sets a lane). Other tiers' lanes and tenants' own lanes would starve.
  - A session that is not pinned is pinned lazily at its first prepare, not at creation (`workspaces/impl/manager.py:147-157`).

**3. Workspace isolation and egress — 5.**
- **Spec:** "Pinned, Probed, Refused" and "Egress" are among the best-specified parts of the repository.
- **Implementation:**
  - The container backend is real: all capabilities dropped, `no-new-privileges`, network `none` or bridged (`infra/.../workspaces/container.py`).
  - The executor gets a fresh container per run.
  - Refusal parks the loop on `resource` before the first model call.
- **What held it back:**
  - **No VM or microVM provider exists.** Yet the host's `vm` probe passes on `/dev/kvm` plus a binary (`apps/host/.../probe.py:163-177`), with no VM transport wired. That contradicts PLC-13.
  - **The egress allowlist is never enforced.** `egress_decision` has no production caller, and the container provider refuses `ALLOWLIST` outright (`container.py:155-160`). The design fails closed, which is right, but only `none` or `open` egress works.
  - **The cloud deployment prepares no workspace** (`ACME_WORKSPACE_BACKEND="none"`, `environment/main.tf:562`). There is no cloud host pool, so cloud-placed sessions park.

**4. Trust, identity and secrets — 8.**
- **Design:** the four identities are the cleanest model of the four systems (spec, "Four Identities").
- **Implemented:**
  - `CallAudit` refuses one credential standing for two identities (`om/trust/types/identities.py:52-79`).
  - Outside text is labelled by the platform from its origin (`intake/rules.py:159-205`).
  - The rule of two is enforced at the tool gate.
  - Owner's ceilings come only from a local file on the host (`apps/host/.../ceilings.py`). A compromised control plane cannot widen them.
  - Operator content access is a separate, time-limited, audited grant (`trust/impl/operator.py:52-91`).
  - Secrets are stored by name and resolved where the call runs.
- **What held it back:**
  - All four identities appear only on tool-call audit entries.
  - `link_account` and `approve_from_chat` have no route. So "a mapped user instructs" and chat approvals are dead paths in a deployment.
  - The KMS key service cannot report destruction (`retention/impl/keys.py`), so the cloud's revocation proof records `reported: False`.

**5. Failure semantics and durability — 8.**
- **Implemented, with tests:**
  - A new writer epoch per run, refused when stale at storage (`steps/storage/impl/postgres.py:222`), and refused again at relay send and claim.
  - `exec` ids derived from the idempotency key (`relay/rules.py:57-63`).
  - An `unsafe` item whose lease expires completes `interrupted` and is never requeued (`relay/impl/manager.py:637-659`).
  - A shared outage signal per provider and credential.
  - Holds settled from the provider's bill.
  - Unsafe-vs-repeatable classification at the relay is a decision none of the adjacents makes.
- **What held it back:**
  - Relayed file operations are keyed by `new_id()`, not by the request (`relay/impl/transport.py:217`).
  - The occurrence counter lives only in process memory.
  - Expired approvals are not a sweep duty, against spec "Failure at Fleet Scale".

**6. Evidence and validation — 7.**
- **Implemented:**
  - The result gate refuses a success on a dirty tree, at the wrong head, or on runs its executor did not write (`om/evidence/rules.py:264-323`).
  - Validation runs in a fresh no-egress container, with protected files checked by digest (`workspaces/impl/executor.py:179-279`).
  - Touching a protected path voids validation.
  - Clopper-Pearson and Wilson bounds, a sequential test, and Bonferroni correction are code (`evidence/rates.py`).
- **What held it back:**
  - Several parts are modeled but not wired: `record_inference` (hypotheses and findings), `record_run` for the agent's own runs, and the acceptance harness and scanner have no production caller.
  - The gate does not require a baseline; the prompt asks for one (`platform_agents/kinds.py:101`).
  - Baseline and candidate trials are not interleaved in validation.
  - The executor's image is a tag, not a digest.
  - A run that declares no dependencies defaults to `real`.
  - `run_command` is not path-gated, though the diff check still catches protected edits.

**7. Cost, budgets and metering — 7.**
- **Implemented:**
  - One versioned price row is read by the cap and the bill.
  - Spend fails closed and never falls back to the platform key (`billing/rules.py:156-231`, `billing/root.py:85-97`).
  - The ledger is append-only through `REVOKE UPDATE, DELETE` (`om/migrations/sql/activity/202610032301_money_ledger.up.sql:77`).
  - Holds draw from buckets in a fixed order.
  - Windows follow the tenant's time zone.
  - The matrix works: the most specific row wins, the catch-all row is required to publish, versions are pinned per session, eligibility filters include fallbacks, and retirement re-resolves.
- **What held it back:**
  - Usage is summed three ways, against "one aggregation".
  - The price book keeps only the version in force (`om/root.py:908`), so a hold priced at an older version settles with no price.
  - "Qualified by benchmark" is a `passed: bool` an operator posts, and the seed sets it true for every fill.
  - There is no payment provider.

**8. Intake and feedback return — 8.**
- **Implemented:**
  - Webhooks are signature-checked, queued, then routed by session, then pull request, then branch (`om/intake/impl/manager.py:268-286`).
  - The wake/wait table in spec "Feedback Routing" is code (`intake/rules.py:73-99`), with one test per row.
  - Automations run as their creator or principal, carry caps, ignore their own sessions' events, stop at a hop limit, and record every firing.
  - Playbook gates only narrow policy, and unreviewed knowledge is never recalled.
- **What held it back:** the account-linking gap from criterion 4, and automations cannot invoke a playbook although the spec says they may.

**9. Watching and steering — 8.**
- **Implemented:**
  - Realtime hints are carried apart from scoped, expiring live-read handles (`om/watch/rules.py:49-86`).
  - Each stream has a bounded buffer that drops the oldest parts for a slow reader.
  - Take control and give back run commands as relayed `exec` work, recorded and attributed to the person (`watch/impl/manager.py:187-280`).
- **What held it back:** mirrors are optional in the spec and absent in the code.

**10. Extensibility and contract clarity — 7.**
- **Strengths:**
  - Product kinds register exactly like platform kinds (spec, "Kinds of Work").
  - `exec` is a versioned public type with a floor.
  - The results contract has a strict schema with a compatibility check before anything runs.
  - Each extension point has a scaffold skill.
- **What held it back:**
  - Extension happens by rendering a fork and merging releases, not through a stable API with a deprecation policy.
  - The relay, control-stream and live-read wire protocols are explicitly out of scope ("What This Spec Does Not Cover"), so a third party cannot build a compatible host from the spec alone.

**11. Operability and testability — 7.**
- **Strengths:**
  - About 2,900 test functions, plus 552 shared contract tests run against in-memory and Postgres stores.
  - A scripted model provider is used across 34 test files.
  - Twins stamp their provenance and refuse to run in deployed environments.
  - The dashboard is declared as code, and `distro-check` enforces bounded labels.
  - All six operational skills exist under `.agents/skills/`.
- **What held it back:**
  - The telemetry round trip stops at the host: no request id reaches it (`services/api/.../types/relay.py:75-87`).
  - There is no general replay harness.
  - `distro-check` decides only 3 of 106 lenses.
  - Operating the platform is heavy: Postgres, KMS, Terraform, a host install, a portal, several workers.

## Where it differs

- **Stronger: validation runs apart from the agent.**
  - *Decision:* the result gate accepts only results written by a separate executor, at the delivered head, under protected checks.
  - *Versus:* OpenHands' critic is a prediction, and Copilot's tests run in the agent's own environment.
  - *What it buys:* a "success" is evidence, not the agent's word.
- **Stronger: unsafe side effects are never repeated.**
  - *Decision:* relayed calls are keyed, and a call whose effect is `unsafe` completes `interrupted` instead of being requeued.
  - *Versus:* Temporal gives at-least-once activities and leaves idempotency to the application; OpenHands states its tools are not idempotent.
  - *What it buys:* a crash never runs a destructive command twice.
- **Stronger: the guard nearest the machine holds.**
  - *Decision:* hosts pull, and owner's ceilings are kept only on the host.
  - *Versus:* Copilot's firewall does not work on self-hosted runners, and OpenHands' control plane creates the sandboxes itself.
  - *What it buys:* a compromised platform cannot widen what a customer's machine does.
- **Stronger: spend fails closed.**
  - *Decision:* one ledger, one price source, holds before calls, and nothing spent when no one can tell who pays.
  - *Versus:* OpenHands Cloud documents budget alerts; Temporal has nothing.
- **Weaker: isolation is not implemented to the level specified.**
  - *Decision:* OpenHands ships Sysbox, gVisor and Kata options with private-range egress blocks; Copilot runs every session in a fresh Actions VM behind a real, if partial, firewall.
  - *What it costs distro_gentic:* no VM backend, no enforced allowlist, and a cloud placement that cannot prepare a workspace. Its strongest spec section is its weakest code.
- **Weaker: replay.**
  - *Decision:* Temporal's deterministic event-history replay, with a `Replayer` and recorded histories.
  - *What it costs distro_gentic:* it rebuilt leases, sweeps and epochs on Postgres and has no generic way to replay a run as a test.
- **Weaker: extension contract.**
  - *Decision:* OpenHands' SDK keeps old events loadable, deprecates over at least 5 minor releases, and checks API breakage in CI.
  - *What it costs distro_gentic:* a product upgrades by merging a fork, so contract breaks show up as merge conflicts.
- **Broader:** distro_gentic owns money, evidence, intake routing and the customer's wall. Temporal leaves all four to the application. Copilot owns intake from many trackers, but in a single-repository, single-PR, 59-minute shape.
- **Narrower:** distro_gentic delegates the agent loop to `agentic_core`. OpenHands owns its loop, tools and SDK in one place.
- **Different: how work reaches a machine inside a wall.** distro_gentic relays `exec` work to customer hosts; Temporal workers poll task queues; Copilot uses self-hosted runners. All three are pull-based.
  - The relay wins when the brain must stay in the cloud and only tool calls run inside the wall.
  - Temporal's model wins when the whole workflow can run beside the data.
- **Different: rules first vs code first.**
  - distro_gentic states the rules first and holds code to them through review; the adjacents document code as it is.
  - Rules first wins for invariants that cut across the code, such as identities, the wall and money.
  - Code first wins on how faithfully docs match runtime: here, 3 of 106 lenses are machine-checked.

## What I would change

1. **Enforce egress as specified.** Add a per-workspace egress proxy that filters by destination and method, call `egress_decision` from it, and set `enforces_allowlist` only when the probe confirms it. Moves criterion 3 by about +2.
2. **Stop the `vm` overclaim and close the cloud gap.** Advertise `vm` only when a VM transport is wired. Either add a cloud host pool to Terraform or say in the spec that the scaffold has no cloud workspaces. Moves criterion 3 by +1 and criterion 2 by +0.5.
3. **Wire or delete the dead paths.** These are `record_run` for agent runs, `record_inference`, the acceptance harness, `link_account`, `approve_from_chat` and `approve_call`. Then add a `distro-check` rule that no manager method lacks a production caller. Moves criterion 6 by +1, criterion 8 by +0.5 and criterion 4 by +0.5.
4. **Give lenses Shape paths and grow `distro-check`.** Today zero of 106 lenses name a scaffold file, and 3 are decided by code. Moves criterion 1 by +0.5 and criterion 11 by +1.
5. **Harden the result gate.**
   - Require a baseline at the gate.
   - Interleave baseline and candidate trials on one executor.
   - Re-verify the results hash at the gate.
   - Pin the executor's image by digest.
   - Make a run that declares no dependencies `unavailable`, not `real`.
   
   Moves criterion 6 by +1.
6. **Make money match its own invariants.**
   - Use one usage aggregation.
   - Keep past price versions in the price book.
   - Make matrix qualification reference a benchmark record instead of a boolean.
   
   Moves criterion 7 by +1.
7. **Close the remaining durability gaps.** Key relayed file operations by the request's idempotency key, persist the occurrence counter, and make re-asking expired approvals a sweep duty. Moves criterion 5 by +0.5.
8. **Deploy a runner per lane.** Have Terraform deploy a runner for each lane in use. Moves criterion 2 by +0.5.
9. **Pin the spec's engine links.** Point them at v0.8.0 as the lenses do, and state a minimal versioned envelope for the relay and control stream. Moves criterion 1 by +0.5 and criterion 10 by +0.5.

## Method

- **distro_gentic:**
  - Read `main` at `76ed581` (v0.9.0, 2026-10-07).
  - Read the spec, README, `AGENTS.md`, `CHANGELOG.md`, `lenses/README.md` and `lenses/placement.md` in full, and every lens's header, severity and check line.
  - Read the scaffold through `git diff scaffold main` and three parallel code audits (placement and isolation, evidence and money, intake, trust and operations), each citing file and line.
  - Spot-checked the main gap findings myself: `main.tf:562`, `container.py:155-160`, `probe.py:163-177`, and the runner's lane setting.
  - I ran no tests.
  - I did not read the other evaluators' reports and scores under `benchmark/runs/`, to avoid anchoring.
- **OpenHands:**
  - Read shallow clones at `software-agent-sdk@91ac058a` (v1.53.0), `OpenHands@6e815714` (Canvas v1.25.0), `docs@273592c7` and `automation@b43294c0`, all 2026-10-07.
  - The Cloud and Enterprise server source is not public, so criteria 2 and 7 rest on docs alone and are low confidence.
- **Copilot cloud agent:**
  - Read about 30 docs.github.com pages on 2026-10-07; they show no last-updated date. Also read changelog posts from 2026-04-03 to 2026-10-02.
  - Concurrency, isolation between sessions beyond "ephemeral Actions environment", and crash recovery are not documented, so criteria 2, 3 and 5 are low confidence.
- **Temporal with OpenAI Agents:**
  - Read `temporalio/ai-integrations@41e64e9` (`openai_agents` v1.1.0), sdk-python tag 1.34.0, and the docs integration page, all 2026-10-07.
  - Fetches of two core platform docs pages were refused by this session's permissions, and I did not retry them.
  - Priority and fairness were confirmed only from search results.
  - Namespace security, signals and updates, queries, and the Web UI were not read in primary sources, so criteria 2, 4, 8 and 9 are low or medium confidence.

Sources:
- [Temporal: Task Queue Priority and Fairness](https://docs.temporal.io/develop/task-queue-priority-fairness)
- [Temporal blog: Task Queue Priority and Fairness](https://temporal.io/blog/task-queue-priority-and-fairness-your-task-queue-your-way)
- [Temporal: OpenAI Agents SDK integration](https://docs.temporal.io/develop/python/integrations/openai-agents)
- [temporalio/ai-integrations, python/openai_agents](https://github.com/temporalio/ai-integrations/tree/main/python/openai_agents)
- [OpenHands SDK docs](https://docs.openhands.dev/sdk)
- [GitHub Docs: Copilot cloud agent risks and mitigations](https://docs.github.com/en/copilot/concepts/agents/cloud-agent/risks-and-mitigations)
- [GitHub Docs: customize the firewall](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-the-firewall)
- [GitHub Docs: Copilot billing](https://docs.github.com/en/copilot/concepts/billing-and-usage/organizations-and-enterprises/billing)