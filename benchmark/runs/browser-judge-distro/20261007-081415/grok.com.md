# grok.com

- URL: [redacted]
- Model: Expert
- Effort: none
- Sent: 2026-10-07T08:27:44Z
- Finished: 2026-10-07T08:36:20Z (date -u at the end of poll 5, the first of two polls whose answer matched, with Enter voice mode at poll 6)
- Status: ok
- Score: 81/100
- Read: 9580f8f524a7 on main (2026-10-07, release 0.7.0)
- Polls: 6
- Note: none

## Answer

Score: 81/100

## Classification

A closed-loop, cloud-first fleet platform: many tenants, unattended sessions lasting days, on machines it does not always own, with work arriving on its own and the world's answer returning to the same session (`distro_gentic_spec.md`, How to Read This, The Core).
Abstraction level: a platform spec plus a domain-free scaffold, above an agent engine and a general software guideline, below a product (`README.md`; spec, The Repository).
Owns placement and the brain/hands split, workspace lifecycle and isolation, intake and automations, the evidence protocol and result gate, the trust wall and four identities, the ledger and model matrix, watching and hand-over, and fleet recovery.
Delegates one agent's loop to `agentic_core`, the queue, gateway, tenancy, and storage roles to `swe_guidelines`, and agent-kind prompts, wire protocols, default timeouts, console screens, the price table, and the deployment threat model elsewhere (spec, What This Spec Does Not Cover).
It is not an agent framework, a workflow engine, a sandbox product, or a billing service.
Category: closed-loop agent fleet platform. That fits better than "agent framework" or "orchestrator" because the loop and the graph are not what it owns; the fleet's placement, wall, money, evidence, and return path are.

## Adjacents

Cursor Cloud Agents, docs read 2026-10-07 (`choose-runtime`, private workers): the closest overlap, because the agent loop stays in Cursor's cloud and tool execution runs on a managed VM or an outbound worker pool the customer operates.
GitHub Copilot coding agent / cloud agent, GitHub Docs as fetched 2026-10-07: overlap on unattended intake from an issue or pull request, an ephemeral Actions workspace, session logs, and comments that continue the same task.
LangGraph Platform / LangSmith Deployment, platform-architecture concept page plus durable-execution docs current as of 2026: overlap on durable runs, a worker pool, checkpoints, streaming, and human interrupt, not on the wall or the ledger.

## Rubric

| Criterion | Measures | A 10/10 | Weight |
|---|---|---|---|
| Conceptual model | Whether control, brain, hands, and records are few, named, and non-overlapping, and a session's work kinds have one meaning | Every new concern lands in one plane; invariants are few and each links to the section that enforces it | 12 |
| Engine and product boundary | Whether the platform owns only what a fleet adds, and a product extends it without forking the loop or the queue | Written seams; the platform's own kinds go through the same registries a product uses | 9 |
| Placement and scheduling | Where the loop and tool calls run, pinning, fairness, and what a lost claim may still write | Any runner resumes any session; a pin waits rather than moving; a neighbor cannot spend the tenant's attempts | 10 |
| Isolation and the wall | Probe-and-refuse isolation, egress, pull-only hosts, and secrets that must not cross | Hosts pull, advertise only what they probed, hold ceilings the platform cannot raise, and refuse an isolation they cannot give | 12 |
| Identity, trust, retention | Executor, principal, spender, and actor; untrusted text; sealing and retention | The four never collapse; outside text cannot instruct; tightening retention reaches back; content keys are tenant-revocable | 10 |
| Money and the model fleet | One ledger, one price, rate versus spend, fail-closed, a versioned matrix | Unknown payer spends nothing; a running session does not silently change fill; rate and spend park for different reasons | 8 |
| Intake and evidence | Work in, feedback to the same session, provenance, and the gate that may call success | Success is refused unless protected checks passed at the delivered version, on results the agent did not write | 12 |
| Watching and hand-over | Live view, steering, and a person taking the workspace | The live view is a window on the record; a person's commands are attributed runs; a mirror cannot block the session | 6 |
| Failure at fleet scale | Leases, epochs, effect-based retry, outage parking, settlement of holds | A lost runner cannot write; an unsafe call is not repeated; an outage parks the fleet and wakes it staggered | 11 |
| Operability and coherence | Ops tasks, cross-hop correlation, and agreement of spec, lenses, and scaffold | A repeating task is a skill with a credential boundary; deviations are recorded; a specified plane exists in the scaffold | 10 |

## Scores

| Criterion | Weight | distro_gentic | Cursor Cloud Agents | Copilot coding agent | LangGraph Platform |
|---|---:|---:|---:|---:|---:|
| Conceptual model | 12 | 9 | 8 | 6 | 7 |
| Engine and product boundary | 9 | 8 | 5 | 4 | 8 |
| Placement and scheduling | 10 | 8 | 7 | 5 | 6 |
| Isolation and the wall | 12 | 8 | 7 | 5 | 3 |
| Identity, trust, retention | 10 | 8 | 4 | 5 | 4 |
| Money and the model fleet | 8 | 8 | 3 | 2 | 2 |
| Intake and evidence | 12 | 9 | 5 | 6 | 4 |
| Watching and hand-over | 6 | 7 | 6 | 6 | 7 |
| Failure at fleet scale | 11 | 8 | 5 | 4 | 8 |
| Operability and coherence | 10 | 7 | 5 | 5 | 6 |
| Weighted | 100 | 81 | 56 | 49 | 55 |

Cursor, Copilot, and LangGraph money, identity, and failure scores are low confidence where the public docs do not specify the mechanism. Scopes differ: LangGraph specifies worker scheduling, not host placement; Copilot specifies a task environment, not a ledger.

## distro_gentic, criterion by criterion

Conceptual model scores 9. The Core lists eight invariants, each linked to a section, and At a Glance splits control, brain, hands, and records. Sessions Are Work makes one session into `loop`, `exec`, `workspace`, and platform work, each claimed where its environment is. Workspaces and Isolation calls the workspace a cache: the branch and artifacts live elsewhere, and a session that merely exists holds no machine. The dual transport is the limit. A cloud workspace needs no item and uses a direct transport (Sessions Are Work); a wall host uses keyed `exec` work (The Relay Transport). ADR 2026 then says a deployed runner prepares no workspace, and an unpinned cloud session has none until a future pool. The model is clear; one plane is specified and not yet a claimant.

Engine and product boundary scores 8. How to Read This refuses to repeat the guideline or the engine. ADR 2025 and ADR 2029 put a product's work kinds and claimants through the same enrollment and claim path a host uses; ADR 2031 does the same for automation actions. The scaffold is domain-free (`scaffold/README.md`), and kinds are declared once in `PRODUCT_KINDS` (session runner README). What holds it back is that The Agents a Platform Ships names engineer, analysis, planner, and assistant as platform agents, while the runner README says kinds are the product's. A reader of only this spec also cannot check a guarantee that is only a link into `agentic_core`.

Placement and scheduling scores 8. Fair Share puts loop work in a lane per plan tier, with a tenant lane if bulk still crowds neighbors, and enforces concurrency at claim: over the limit, the item returns with a delay and spends no attempt (PLC-02, ADR 2002). Session Runners says any runner resumes any session because it holds nothing that cannot be rebuilt, and a lost claim stops writes via the engine's writer epoch. Placement pins a session to a host pool and will not move it to the cloud unless a principal changes the pin. Lease lengths and fairness weights are named as out of scope (What This Spec Does Not Cover), and the cloud pool that At a Glance draws is the deferred pool of ADR 2026.

Isolation and the wall scores 8. Workspace Hosts is the strongest designed boundary in the repo. A host is a gateway client, enrolls once, advertises only isolation modes it probed, is handed work filtered by its identity, and enforces owner ceilings the platform cannot raise. That last rule is recorded as a deliberate deviation, DEL-01. Pinned, Probed, Refused parks the loop on `resource` rather than weakening isolation; egress is an allowlist; a bare directory runs as a dedicated user or the host refuses. The host README implements probe, ceilings, enrollment, and a metadata-endpoint refusal under open egress. ADR 2026 admits the macOS ceilings are the owner's word, not a wall. The relay's wire protocol is explicitly uncovered, so two hosts can still diverge on the stream.

Identity, trust, retention scores 8. Trust, Four Identities keeps executor, principal, spender, and actor apart, and says confusing any two is a defect. The agent holds no authority; a lapsed principal parks tool calls; a chat approval counts only as a mapped user with the approve permission (WAL-01 through WAL-03). Secrets by Placement stores names only and resolves the secret where it is used; a cloud secret never crosses the wall. Data, Retention, and the Wall seals step content under a per-session key the tenant can revoke, snapshots retention at creation, lets tightening reach existing sessions, and records key destruction as the key service reported it. The threat model is left to each deployment, and the untrusted-text render is the engine's, with the platform only setting origin.

Money and the model fleet scores 8. Money defines one aggregation for every view of usage, limits that count settled spend plus open holds, an abstract unit beside usage and charge, and an append-only ledger whose hold draws buckets in a fixed order. Credits count only after a signed confirmation; a top-up never raises a limit; rate and spend park for different reasons (MNY-03, MNY-05, MNY-07). One Price Source fails closed when the payer is unknown. Models Are a Fleet Decision versions the matrix, keeps a running session on the version it started with, and re-resolves only at the next loop on retirement, with a `switched` step. The price table and anomaly thresholds are out of scope, so the fail-closed rule has no numeric contract.

Intake and evidence scores 9. What Closes a Loop states seven promises the platform enforces rather than hopes for. The feedback table in Work In, Results Out wakes a principal's message and a failing check, waits on a bot and a passing check, and treats a person's push as a hand-over. Automations run as creator or automation principal, ignore their own events unless declared, and stop at a hop limit. Evidence requires version, environment, and a provenance of `real`, `twin`, `double`, or `unavailable`; a double never validates. Validation runs on a fresh executor from the delivered commit, and the result gate refuses success unless that policy passed at the committed head with a clean tree (EVD-06, EVD-10). Statistical claims must use a declared bound and count every trial. The results schema is versioned, but the collector's wire is not, which is the remaining gap.

Watching and hand-over scores 7. Watching and Steering splits a realtime hint-and-record channel from a live read through a short-lived scoped handle, and says a live part is a cache whose loss costs nothing (WAT-01, WAT-03; deviation NET-20). Take Control parks the loop on a hand-over and records the person's commands as `exec` runs attributed to them, over the same stripped environment. A mirror subscribes and the session never waits on it. The stream service's technology and the console's screens are out of scope, so the handle's authorization is "scoped" without a contract, and there is no specified bound on buffer loss beyond "bounded."

Failure at fleet scale scores 8. Failure at Fleet Scale puts recovery on the guideline's sweep, which every cloud worker runs and hosts do not; a beat is a signal, never a trigger (FLT-07). An expired loop is requeued under a new writer epoch. An `exec` item is requeued only when its effect is `read_only` or `idempotent`, and only to the host that holds the workspace; an `unsafe` one completes `interrupted` (The Relay Transport, PLC-20). A hold nobody settled settles at provider-reported usage, else at its full amount, and is released only when the provider provably did not bill. An outage signal in the shared cache parks sessions within a second, and an unreachable cache is a declared degraded answer rather than a silent proceed-as-healthy. "Within a second" assumes that cache, and lease lengths are unnamed.

Operability and coherence scores 7. Operations makes repeating tasks skills with a credential boundary (`ops-session-stuck`, `ops-host-idle`, `ops-provider-outage`, `audit-matrix-spend`), bounds dashboard labels, and follows one request id across runner, host, and steps. Lenses are stricter than the spec and point at scaffold files (`lenses/README.md`). Deviations are a table, not a footnote. The score stops at 7 because At a Glance draws cloud workspace hosts with a direct transport, while ADR 2026 and the host program only realize the pull path, and almost every high-severity lens is `Check: review` rather than a gate `make check` can fail.

## Where it differs

Stronger: the result gate refuses a success the agent's own workspace wrote, and provenance separates `real`, `twin`, and `double` (Evidence, The Result Gate); Copilot records session logs and a security pass, Cursor records transcripts and diffs, and neither specifies a gate that can reject the claim. The same gap is why the four identities and the fail-closed ledger have no equivalent in the three public architectures.
Weaker: LangGraph's durability modes (`exit`, `async`, `sync`) and pending writes say exactly which crash window loses a step; distro_gentic names the writer epoch and the sweep, then leaves lease length and the cache that must park the fleet "within a second" to each system. Cursor's private worker also states a narrower crossing rule than the spec does: the file stays in the network and only the chunk the model needs leaves, while distro_gentic stores every tool result, source included, in platform history unless a deny-list says otherwise (Placement).
Narrower than Cursor and Copilot on the product surface, broader on the fleet contract: it does not own a console, a price table, or a coding agent's prompts, and it does own host ceilings the control plane cannot raise, retention as a snapshot, and automations that cannot chain past a hop limit. LangGraph is broader as a graph runtime and narrower as a fleet: the application owns isolation, evidence, and money.
Different: Cursor keeps the loop in its cloud and tools on an outbound worker, the same split as Session Runners, but binds a cloud-agent instance to a dedicated worker and restores a snapshot on follow-up. distro_gentic treats the workspace as a cache any host in the pool may rebuild, and any runner may resume the session. The dedicated-worker choice wins when the checkout is expensive to rebuild; the cache choice wins when hosts die and sessions last for days.

## What I would change

Reconcile At a Glance with ADR 2026: either the cloud hands are the same host program on a direct transport, or the diagram stops drawing a pool the scaffold refuses. Operability and conceptual model, about one point each.
Specify the relay and control-stream contract that What This Spec Does Not Cover currently omits: idempotency key, version floor, and what a host does with an unknown field. Isolation and failure, about one point combined, without choosing a technology.
Name lease, grace, and hop limit as required parameters whose unset behavior is fail-closed, still without default numbers. Failure, about half a point.
Move engineer, analysis, planner, and assistant out of the platform's owned kinds, or mark them as the reference product's. Engine and product boundary, about half a point.
Turn the high-severity lenses whose shape already points at scaffold code into gates `make check` can fail, and leave the narrative lenses as review. Operability, about half a point.

## Method

Read `distro_gentic` at `9580f8f524a7` on `main` (2026-10-07, release 0.7.0): the spec in full, lens index plus `placement.md` and `money.md`, the other lenses' rule titles, session-runner and host READMEs, ADRs 2003, 2005, 2023, 2026, and 2029, and the 2000-series ADR titles. Cursor from the choose-runtime and private-workers docs fetched 2026-10-07; Copilot from GitHub Docs on the cloud agent environment, session logs, and firewall fetched the same day; LangGraph from the platform-architecture concept page and the 2026 durable-execution docs. Cursor and Copilot identity, money, and crash recovery, and LangGraph isolation and billing, are scored only from what those pages specify.
