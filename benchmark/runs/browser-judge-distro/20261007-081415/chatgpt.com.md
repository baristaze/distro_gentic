# chatgpt.com

- URL: [redacted]
- Model: Latest
- Effort: High
- Sent: 2026-10-07T08:19:02Z
- Finished: 2026-10-07T08:33:50Z (date -u when poll 2 saw Worked for 11m 43s above the answer)
- Status: ok
- Score: 89/100
- Read: current main at commit 9580f8f
- Polls: 2
- Note: none

## Answer

Score: 89/100

## Classification

- **What it solves:** `distro_gentic` solves the infrastructure problem above a single-agent runtime: how to operate many durable agent sessions across tenants, runners, cloud workspaces, and customer-owned hosts while preserving placement, trust, cost, evidence, intake, feedback, and operator control. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/main/distro_gentic_spec.md)
- **Abstraction level:** application infrastructure between the agent engine and the product. `agentic_core` owns one agent's loop; `distro_gentic` turns that loop into an operable fleet. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/main/distro_gentic_spec.md)
- **Architectural role:** a durable multi-tenant control plane plus execution plane around an agent engine, with cloud brains separated from potentially customer-hosted hands. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/main/distro_gentic_spec.md)
- **Core execution model:** durable sessions generate typed work; stateless cloud session runners claim leased work; workspaces execute locally or through outbound-only hosts; writer epochs prevent stale actors from mutating session state; sweepers repair abandoned work. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/main/distro_gentic_spec.md)
- **Primary abstractions:** session, step, work item/lane, agent kind, placement, host/pool, workspace, relay execution, evidence/result gate, principal/actor/spender/executor, budget/hold/ledger, model matrix, event/intake/automation, and retention/privacy policy. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/9580f8f/scaffold/acme_root/om/README.md)
- **Extension points:** product agent kinds and work kinds, integrations, infrastructure capability interfaces with twins, tool policy, playbooks, automations, model matrix entries, and product-specific routing/result publication. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/9580f8f/scaffold/acme_root/infra/README.md)
- **What it owns:** fleet lifecycle, placement, queueing, failure recovery, workspace execution boundaries, trust and tenancy, evidence, fleet money, model governance, external intake/feedback, live watching/steering, and operational repair contracts. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/main/distro_gentic_spec.md)
- **What it delegates:** single-agent cognition and loop semantics to `agentic_core`; generic software architecture conventions to `swe_guidelines`; domain semantics, end-user product behavior, and concrete third-party integrations to the consuming product. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/main/distro_gentic_spec.md)
- **What it is not:** not an agent framework, not merely an agent orchestrator, not a workflow engine, not a coding-agent product, and not a generic container scheduler.
- **Category:** **closed-loop agent fleet platform**. That is more precise than "agent orchestrator" because orchestration is only one responsibility. The architecture also owns the security wall, execution substrate, fleet economics, evidence, intake/feedback loop, and operator model.

## Adjacents

- **OpenAI Agents API:** the closest architectural adjacent overall. It provides a managed agent harness, durable sessions, orchestration/recovery, and hosted or self-hosted execution environments. Its harness/environment split, including an outbound-only self-hosted executor, overlaps strongly with `distro_gentic`'s brain/hands and host-relay model. [OpenAI Developers](https://developers.openai.com/api/docs/guides/agents-api/overview?utm_source=chatgpt.com)
- **GitHub Copilot cloud agent:** the closest end-to-end productized fleet analogue. It receives work from issues, APIs and external systems, runs unattended cloud sessions, exposes live monitoring and steering, supports event/scheduled automation, and returns work through GitHub's review loop. The overlap is intake, autonomous execution, sandboxing, watching, feedback, and result handoff. [GitHub Docs](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/start-copilot-sessions?utm_source=chatgpt.com)
- **Temporal:** the closest infrastructure adjacent for the durable-execution half of the architecture. Temporal overlaps with session durability, task queues, leases/retries, external messages, recovery, and worker execution, but deliberately does not own agent-specific workspace security, evidence gates, model governance, or fleet economics. [Temporal Documentation](https://docs.temporal.io/encyclopedia/event-history?utm_source=chatgpt.com)

I would **not** use LangGraph, PydanticAI, or the Claude Agent SDK as the primary comparison set. Their center of gravity is the agent/application runtime. `distro_gentic` begins one architectural layer above that.

## Rubric

I freeze the following rubric here. All four systems are scored against exactly these definitions and weights.

| Criterion | What it measures | A 10/10 architecture | Weight |
|---|---|---|---:|
| **Architectural model & boundaries** | Quality of the conceptual decomposition and ownership boundaries between fleet platform, agent engine, execution environment, and product | Few orthogonal primitives, unambiguous ownership, one-way dependencies, no duplicated lower-layer concerns | 12 |
| **Fleet execution, placement & recovery** | Durable scheduling, leases, fairness, placement, retries, stale workers, crash recovery and effect semantics | Explicit deterministic dispatch, strong backpressure/fairness, safe recovery, no duplicate unsafe effects, precise placement/failover semantics | 14 |
| **Workspace & execution isolation** | Workspace lifecycle, hosted/customer compute, isolation, egress and executor credentials | Verified isolation, least privilege, explicit egress/secrets boundaries and safe hosted/self-hosted execution | 12 |
| **Tenancy, trust & data boundary** | Tenant fence, authorization, attribution, secrets, privacy, retention and operator access | Tenant and identity provenance everywhere, least privilege, explicit trust crossings, revocable data access and auditable administration | 13 |
| **Evidence, determinism & testability** | Durable history, reproducibility, independent result validation, twins/doubles and replay characteristics | Every material claim reconstructable; exact delivered version independently validated; failures and inconclusive outcomes first-class | 12 |
| **Closed-loop intake, feedback & steering** | Work intake, result return, feedback-to-session routing, automation, watching and takeover | Complete event-to-work-to-result-to-feedback loop with bounded autonomous execution and effective human control | 10 |
| **Cost & model governance** | Fleet budgets, usage settlement, price policy, model routing/qualification and provider failure | Atomic pre-spend enforcement, auditable settlement, single versioned price source and deterministic qualified model policy | 9 |
| **Extensibility & contract clarity** | Typed/versioned APIs and clean product/infrastructure extension points | Explicit, versioned, capability-oriented extensions with compatibility rules and no reach-through into internals | 8 |
| **Operability & observability** | Metrics, traces, audit, dead letters, sweepers, operator surfaces and repair procedures | Fleet failures diagnosable and repairable from safe supported surfaces with bounded telemetry and clear failure ownership | 6 |
| **Simplicity & developer ergonomics** | Cognitive and operational burden relative to the guarantees obtained | Smallest practical machinery, straightforward local development, coherent defaults and little duplicated operational machinery | 4 |
|  |  | **Total** | **100** |

## Scores

| Criterion | Wt. | distro_gentic | OpenAI Agents API | GitHub Copilot cloud agent | Temporal |
|---|---:|---:|---:|---:|---:|
| Architectural model & boundaries | 12 | **9.3** | 8.8 | 7.8 | 8.8 |
| Fleet execution, placement & recovery | 14 | **8.7** | 7.2 | 6.2 | **9.9** |
| Workspace & execution isolation | 12 | 8.4 | **8.6** | 7.8 | 4.4 |
| Tenancy, trust & data boundary | 13 | **9.3** | 7.2 | 7.6 | 6.2 |
| Evidence, determinism & testability | 12 | **9.3** | 6.8 | 6.5 | 8.8 |
| Closed-loop intake, feedback & steering | 10 | 9.0 | 7.6 | **9.2** | 8.5 |
| Cost & model governance | 9 | **9.4** | 6.2 | 5.5 | 3.5 |
| Extensibility & contract clarity | 8 | 8.8 | **9.3** | 8.8 | **9.3** |
| Operability & observability | 6 | 8.4 | 8.6 | 8.3 | **9.4** |
| Simplicity & developer ergonomics | 4 | 6.7 | **9.0** | **9.0** | 7.2 |
| **Weighted result** | **100** | **89/100** | **78/100** | **75/100** | **76/100** |

These are scores under a **closed-loop agent fleet platform** rubric. Temporal's low workspace or money scores do not mean Temporal is badly designed; those are intentionally application-owned concerns in Temporal. Likewise, GitHub's narrower product scope earns it simplicity that a general platform cannot automatically claim.

## distro_gentic, criterion by criterion

### 1. Architectural model & boundaries: 9.3/10

The strongest decision in the repository is the layering itself. `distro_gentic_spec.md`, particularly **How to Read This Specification**, **The Core**, and **At a Glance**, explicitly refuses to reimplement the single-agent loop and instead frames the system around control plane, cloud brain, execution hands, and records/money. The scaffold largely preserves that split with separate API, maintenance worker, session runner, host, object model, integrations and infrastructure interfaces. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/main/distro_gentic_spec.md)

The score stops below 10 because the architecture has three normative layers, `swe_guidelines`, `agentic_core`, and `distro_gentic`, and several concerns such as budget, privacy and identity necessarily touch more than one layer. The source-of-truth ladder is disciplined, but understanding a platform invariant sometimes requires chasing it through several repositories and then into a lens or scaffold contract. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/main/AGENTS.md)

### 2. Fleet execution, placement & recovery: 8.7/10

**Sessions Are Work**, **Session Runners**, **Placement**, **Hosts**, and **Failure at Fleet Scale** form a coherent execution protocol. One queue shape carries different work kinds; claim-time guards apply fairness and concurrency; loop workers are leased; each resumed writer gets a new epoch; stale writers cannot append steps or issue commands; repeatable effects can be retried while unsafe effects become interrupted rather than blindly repeated. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/main/distro_gentic_spec.md)

That is substantially better than ordinary "put the agent on a queue" architecture.

What holds it back is that durability is assembled from several independently correct mechanisms: durable steps, queue rows, leases, epochs, idempotency keys, relay records and periodic sweep. There is no single replay substrate defining the complete state transition. The spec also explicitly leaves relay/control/live wire protocols and lease/fairness defaults unspecified. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/main/distro_gentic_spec.md)

Temporal is cleaner specifically here because its durable Event History is the canonical recovery substrate: worker failure reconstructs workflow state by deterministic replay. [Temporal Documentation](https://docs.temporal.io/encyclopedia/event-history?utm_source=chatgpt.com)

### 3. Workspace & execution isolation: 8.4/10

The customer-host design is excellent. **Placement and Hosts** requires the host to initiate the connection outward; the cloud cannot dial through the customer's wall. Hosts probe capabilities before advertising them, sessions pin their required isolation instead of silently degrading, the host carries no model/session history/database authority, and owner ceilings are enforced locally so the control plane cannot remotely relax them. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/main/distro_gentic_spec.md)

**Workspaces** also gets several subtle things right: workspace state is treated as cache, durable output lives elsewhere, credentials are stripped, egress is explicitly controlled, cloud metadata access is guarded, and directory isolation is not pretended to be equivalent to VM isolation. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/main/distro_gentic_spec.md)

The specification is ahead of the reference implementation here. The host implementation currently has concrete container support and explicitly refuses bare-directory mode because the required dedicated-user transport does not exist yet. VM/microVM capability appears in the architectural vocabulary without equivalent reference coverage. That is an appropriate refusal, but it means the broad isolation model is partly specified rather than demonstrated. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/9580f8f/scaffold/acme_root/apps/host/README.md)

OpenAI Agents API is marginally ahead on this one criterion because hosted sandboxing is a fully owned platform primitive while self-hosted execution has a deliberately restricted executor key and outbound WebSocket. It still leaves more of self-hosted lifecycle and secret brokerage to the application than `distro_gentic` wants to. [OpenAI Developers](https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted?utm_source=chatgpt.com)

### 4. Tenancy, trust & data boundary: 9.3/10

This is one of the repository's best areas.

The object model distinguishes **executor, principal, spender and actor** rather than collapsing "the agent" into an authority identity. The agent is explicitly never the source of authority. Authorization is checked at use time. Untrusted outside data acquires durable provenance, and combining untrusted material with private data or outward effects invokes stronger policy. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/9580f8f/scaffold/acme_root/om/src/acme/om/attribution/README.md)

Tenancy is an actual object-model invariant rather than a query convention. Privacy adds per-session encryption keys wrapped by tenant keys; retention snapshots policy at session creation and allows later tightening without making later loosening retroactive; operator content access is separate from ordinary operational visibility. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/9580f8f/scaffold/acme_root/om/src/acme/om/tenancy/README.md)

The remaining gap is threat-model closure. The spec itself lists the deployment threat model as out of scope. There is strong logical trust architecture, but less explicit treatment of compromised hosts, control-plane compromise, machine attestation, side channels, and infrastructure-administrator capabilities. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/main/distro_gentic_spec.md)

### 5. Evidence, determinism & testability: 9.3/10

The repository makes a distinction that many agent systems miss: **the work an agent delivers is not the result; evidence about the delivered version is the result**.

Execution evidence records source version, dirty state, environment, host/isolation, check identity/version, parameters, timing, outcome, artifact hashes and provenance. Validation runs separately on a fresh executor against the exact delivered commit, with protected checks sourced independently from the agent's modified tree. Baseline execution is first-class. Success, failure and inconclusive are distinct gate outcomes. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/9580f8f/scaffold/acme_root/om/src/acme/om/evidence/README.md)

The real/twin/double/unavailable provenance vocabulary is particularly good because it prevents a test double from silently becoming "validation." Statistical checks are also treated as statistical rather than collapsed into a Boolean pass. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/main/distro_gentic_spec.md)

It is not a 10 because this is not full deterministic replay. The request window can be reconstructed deterministically from durable steps, but arbitrary external tool effects cannot be replayed like Temporal Workflow code. For unsafe effects, the architecture correctly chooses uncertainty/interruption over lying about exactly-once execution. That is safe, but less powerful than a universal replay model. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/9580f8f/scaffold/acme_root/om/src/acme/om/windows/README.md)

### 6. Closed-loop intake, feedback & steering: 9.0/10

`distro_gentic` is genuinely closed-loop, not merely background execution.

**Work In, Results Out** maps external events into sessions and maps resulting work back outward. Review comments, reopen/reassign events and CI failures can wake the same durable session rather than start unrelated conversations. Automations have explicit principals, limits, loop prevention and hop bounds. Watching uses durable records plus disposable live streams, while steering enters the agent's inbox rather than mutating its state out-of-band. Human takeover retains the same workspace and evidence chain. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/main/distro_gentic_spec.md)

GitHub Copilot cloud agent slightly edges it in today's demonstrated product loop because GitHub owns both sides of issue/PR/review automation and exposes a polished live session surface. Copilot sessions can be initiated from GitHub and several external systems, monitored live, steered mid-session, and returned directly into a pull-request workflow. [GitHub Docs](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/start-copilot-sessions?utm_source=chatgpt.com)

For `distro_gentic`, the architecture is stronger than the currently domain-free scaffold coverage. Concrete product integrations and result adapters are intentionally delegated, so some of the closed loop remains a contract awaiting a product such as [redacted].

### 7. Cost & model governance: 9.4/10

This may be the most unusually complete subsystem.

**Budgets** does not merely count tokens afterward. A model call acquires worst-case holds transactionally against multiple applicable scopes and windows. Holds are later settled against actual usage, with append-only records and explicit behavior when usage cannot be established. There is one versioned price source rather than dispersed estimates. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/9580f8f/scaffold/acme_root/om/src/acme/om/budgets/README.md)

The **model matrix** then makes model selection governed infrastructure: environment, role, agent kind, plan tier and workload class participate in deterministic resolution; rows must refer to priced and qualified models; sessions pin policy; retirement produces an explicit switch rather than silently changing an ongoing session. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/9580f8f/scaffold/acme_root/om/src/acme/om/models/README.md)

Provider outages and credential-specific failures are also modeled at fleet level rather than interpreted as thousands of unrelated agent failures. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/main/distro_gentic_spec.md)

The missing 0.6 is mostly operational closure: the spec intentionally does not provide the real price table, and eventual reconciliation between internal settlement and provider invoices is not as deeply specified as runtime authorization.

### 8. Extensibility & contract clarity: 8.8/10

The architecture is intentionally domain-free. Infrastructure capabilities expose interfaces with cloud/twin implementations; integrations have their own boundary; product work and agent kinds can be added; results and host protocols are version-conscious; static architecture checkers and lenses reinforce the contracts. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/9580f8f/scaffold/acme_root/infra/README.md)

This is much stronger than a codebase whose "extension model" is simply importing internal implementation classes.

The cost is that extension happens at several registries and composition points: product kinds, work kinds, lanes, claimant types, secret ownership, infrastructure bindings and product routing. The scaffold-as-reference approach also creates an eventual merge/upstream surface for products derived from it. The extension model could be compressed into fewer public concepts.

### 9. Operability & observability: 8.4/10

There is a real operations architecture, not just logging.

Maintenance has explicit responsibility for sweeps, delivery consumption, schedules, purge and outbox work. Operations separates investigator/support/provisioning privileges, discourages humans and agents from direct cloud mutation, requires bounded telemetry labels, and calls out concrete audits for database access, retention, credential lifetimes, model spend and provider behavior. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/9580f8f/scaffold/acme_root/workers/maintenance/README.md)

Request IDs, append-only audit events, dead-letter/requeue paths and fleet sweepers provide good forensic material.

Temporal remains stronger here because visibility, worker/task-queue telemetry and durable execution diagnostics are intrinsic properties of a mature execution substrate rather than contracts assembled by the application. `distro_gentic` also leaves SLOs, disaster-recovery topology, exact stream/queue technology and several operational thresholds open. [Temporal Documentation](https://docs.temporal.io/cloud/slo)

### 10. Simplicity & developer ergonomics: 6.7/10

This is the clear price of the design.

There are excellent simplifying rules: one work-item shape, one result gate, one ledger, one price source, one host program, a unified execution transport, stateless session runners, and explicit ownership boundaries. Those prevent local complexity from becoming semantic ambiguity.

But the whole platform still contains roughly thirty object-model concepts plus API, maintenance, session runner, host, queue leases, sweepers, epochs, sealed storage, retention, key services, budget holds, model matrices, host pools, relay records and several extension registries. The developer must also understand two lower architectural layers. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/9580f8f/scaffold/acme_root/om/README.md)

Much of that complexity is justified by the guarantees being attempted. It is still complexity. Compared with OpenAI Agents API's four primary concepts, Agent, Environment, Session, and Events/Items, `distro_gentic` asks far more of its adopter. [OpenAI Developers](https://developers.openai.com/api/docs/guides/agents-api/overview?utm_source=chatgpt.com)

## Where it differs

- **Stronger:** versus OpenAI Agents API and GitHub Copilot cloud agent, `distro_gentic` makes four-way identity, tenant isolation, local unrelaxable host ceilings, fleet budgets, and independent exact-version result validation first-class architectural invariants rather than primarily application or product policy; this buys much stronger auditability for unattended multi-tenant agents operating behind customer walls. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/9580f8f/scaffold/acme_root/om/src/acme/om/attribution/README.md)
- **Weaker:** versus Temporal, `distro_gentic` implements durability through the composition of queue state, leases, writer epochs, durable steps, idempotency and sweep rather than a single canonical event history with deterministic replay; this gives it agent-specific semantics but creates more recovery surface and more ways invariants can interact. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/9580f8f/scaffold/acme_root/workers/session_runner/README.md)
- **Broader / narrower:** it is broader than Temporal and OpenAI Agents API in fleet economics, customer-wall trust, evidence gating and product-independent intake semantics, but narrower than GitHub Copilot cloud agent as an actual coding product because domain UX, repository workflow semantics and concrete integrations are deliberately left to a product built above it. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/main/distro_gentic_spec.md)
- **Different:** `distro_gentic` fixes the architectural rule that the **brain remains in cloud while the hands may move behind the customer wall**; OpenAI Agents API similarly separates managed harness from self-hosted execution but delegates environment lifecycle to the application, while Temporal moves arbitrary application workers behind task queues. Each wins under a different desired control-plane trust model. [GitHub](https://raw.githubusercontent.com/baristaze/distro_gentic/main/distro_gentic_spec.md)
- **Different:** GitHub Copilot intentionally couples intake, authority, sandboxing and output to the GitHub/Actions security model. That sharply reduces conceptual and operational burden. `distro_gentic` pays substantially more complexity so a consuming product can define the domain and external systems itself. [GitHub Docs](https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-automations?utm_source=chatgpt.com)

## What I would change

1. **Fleet execution +0.5 to +0.8, simplicity +0.3:** collapse the normative recovery semantics scattered across sessions, placement, relay, runner and fleet-failure sections into one explicit state-transition/failure matrix, generated or checked against tests; do not add another recovery abstraction.
2. **Workspace isolation +0.4 to +0.6:** make the supported-isolation matrix explicitly distinguish **specified**, **reference-implemented**, and **conformance-tested** modes; either remove VM/microVM from the current release guarantee or implement the corresponding reference path.
3. **Tenancy/trust +0.4, isolation +0.2, operations +0.2:** fill the deliberately omitted deployment threat model, particularly compromised customer host, compromised control-plane service, cloud administrator, operator, malicious tenant and provider compromise; state explicitly whether hardware/workload attestation is out of scope.
4. **Contracts +0.3, execution +0.2:** specify the relay/control/live protocol **invariants** without choosing transport technology: version negotiation, reconnect semantics, sequencing, idempotency, authentication, cancellation race behavior and terminal-state rules.
5. **Architectural clarity +0.2, developer ergonomics +0.4:** add one generated conformance table mapping each normative invariant to `Specified / Scaffolded / Tested / Product responsibility / Deferred`; this would remove much of the present ambiguity between an excellent specification and the subset the scaffold currently proves.
6. **Extensibility +0.4, simplicity +0.3:** consolidate the several product extension registries into a smaller explicit product-extension contract, ideally one typed composition surface for agent kinds, work kinds, claimant/secret ownership and routing additions.
7. **Operability +0.4:** make fleet failure domains and SLO assumptions normative: maximum lease-recovery delay, sweep convergence, queue backlog objectives, outage fan-out, regional loss assumptions and what must survive control-plane/database loss.
8. **Evidence +0.2:** state the exact boundary of reproducibility more explicitly: deterministic request reconstruction is guaranteed; deterministic replay of external effects is not. This removes any possible inference that writer epochs/idempotency amount to Temporal-style replay.

With those changes, I would expect the architecture to move from roughly **89 to 92-93**, mostly through clarification and consolidation rather than adding features.

## Method

- **`distro_gentic`:** evaluated current `main` at commit **`9580f8f`**, one wording-only spec-title commit beyond release **v0.7.0 / `6babd13`**. I traversed the repository structure and read the normative specification, all eight lens groups, repository source-of-truth/gate documentation, scaffold architecture and service contracts, and the detailed object-model pages governing tenancy, sessions, steps, agents, attribution, privacy, retention, budgets, billing, models, model matrix, windows, tools, evidence, placement, trust, hosts and relay; I also checked the release/changelog and implementation-facing host/session-runner/maintenance/ops documentation. [GitHub](https://github.com/baristaze/distro_gentic/commit/HEAD)
- **Depth caveat:** generated/copied material and routine implementation files were not weighted independently when they merely instantiate an already-read architecture contract. Scores distinguish the normative architecture from the scaffold's proven coverage, particularly around isolation transports and product integrations.
- **OpenAI Agents API:** current public-beta architecture/documentation as of **October 7, 2026**, including overview, hosted environments, self-hosted executor, sandbox security and lifecycle. It was announced September 10, 2026. Fleet scheduling internals and exact recovery implementation are not publicly specified, so those portions of its execution score are **medium confidence** rather than inferred. [OpenAI](https://openai.com/index/introducing-the-agents-api/?utm_source=chatgpt.com)
- **GitHub Copilot cloud agent:** current GitHub documentation as of **October 7, 2026**, covering agent management, session entry points, automations, custom agents, runners/environment configuration, firewall/security and PR/review feedback. Internal fleet scheduling and crash-recovery semantics are thinly documented, so its execution/recovery score is **low-to-medium confidence**. [GitHub Docs](https://docs.github.com/en/copilot/concepts/agents/cloud-agent?utm_source=chatgpt.com)
- **Temporal:** current Temporal architecture documentation as of **October 7, 2026**, with emphasis on Event History/replay, Workflow determinism, Workers/Task Queues, Activities and Workflow message passing. Its low trust/workspace/money scores are **high-confidence scope distinctions**, not assumptions that Temporal unsuccessfully attempted those facilities. [Temporal Documentation](https://docs.temporal.io/encyclopedia/event-history?utm_source=chatgpt.com)

The main architectural conclusion, [redacted]: **89 is not coming from feature breadth. It comes from the repository having a surprisingly coherent answer to the hard boundaries that appear only once you operate agents as a fleet: who is authorized, where execution is allowed, who pays, what survived a crash, what result was actually proven, and how an unattended agent gets back into the real-world loop.** The thing keeping it out of the low 90s is almost the mirror image of that strength: it has chosen to own so many of those guarantees itself that its durability and extension model now need another round of compression.
