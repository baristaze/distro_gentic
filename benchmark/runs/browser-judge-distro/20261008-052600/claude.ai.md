# claude.ai

- URL: [redacted]
- Model: Opus 5.5
- Effort: High
- Sent: 2026-10-08T05:29:49Z
- Finished: 2026-10-08T06:07:33Z (the page's status "Claude finished the response", seen at poll 35)
- Status: ok
- Score: 70/100
- Read: commit a8428906b86a, tag v0.10.0 (2026-10-07)
- Polls: 35
- Note: the new-chat composer held no draft; the composer's permission chip read Auto (Claude runs on its own and pauses to ask if anything looks unsafe), and no line said the product could act on the machine or named a device, before the send or at any poll; right after the send the page showed a banner that the permission mode is set to Auto and includes using connectors and Claude in Chrome, naming no device; no dialog asked to fetch a page or use a tool; the answer names benchmark/ only to say it scores how chat assistants perceive the repository, and names no run or score of one; the first paste from the copy button passed the check but the clipboard changed before it was saved, so the button was clicked once more and that paste is the one saved

## Answer

I'll clone `distro_gentic`, read it in full starting from the spec, then research the closest adjacents and score everything under one frozen rubric.

Score: 70/100

## Classification

- **What it is:** a specification for a multi-tenant control plane that runs agent sessions unattended and closes the loop on them. Work arrives from outside, evidence goes out, and the world's reply returns to the same session. The spec comes with 107 lenses (checkable rules), generated review skills, and a 2,431-file reference scaffold (`acme`).
- **Abstraction level:** it sits above an agent-loop engine (`agentic_core`) and below a product (`[redacted]`). It is a platform layer, not a library.
- **Role in an application:** it is the control, brain, hands, and money planes a product renames and builds its domain on (`distro_gentic_spec.md`, At a Glance).
- **Execution model:**
  - Every session becomes rows in one leased work queue, of kinds `loop`, `exec`, `workspace` and product kinds, each on its own lane.
  - The loop always runs on cloud session runners.
  - Tool calls run on workspace hosts, which pull the work. Some hosts sit inside the customer's network.
- **Primary abstractions:**
  - session, kind of work, lane, placement, host pool
  - workspace (treated as a cache), isolation spec, `exec` item keyed by idempotency key and typed by effect
  - the four identities: executor, principal, spender, actor
  - execution record with provenance, validation policy, result gate
  - ledger and price table, model matrix
  - automation, playbook
- **Extension points:**
  - `PRODUCT_KINDS` registries (`S/om/src/acme/om/product_kinds.py`, ADR 2025), which the platform's own kinds also go through
  - the portal slot (ADR 2042) and the claimant kit (ADR 2046)
  - `distro-scaffold-*` skills for runners, hosts, providers, integrations, agent kinds and automations
- **What it owns:** placement, the relay into a customer's network, workspace isolation and egress, trust and secrets by placement, metering and billing, the model matrix, intake and feedback routing, evidence and the result gate, live watch and take-control, fleet recovery through the sweep.
- **What it delegates:**
  - to the engine: the step loop, writer epoch, steering, budgets gate, agent kinds, history
  - to `swe_guidelines`: the work queue, gateway, realtime, twins, deployment and operations
  - to each deployment: wire protocols, default values, the threat model
- **What it is not:** not an agent framework, not an agent loop, not a durable-execution engine, not a CI system, not a sandbox provider.
- **Category: multi-tenant control plane for closed-loop agent fleets.** "Orchestrator" suggests coordinating agents with each other, which it does not do. "Agent framework" suggests the loop, which it delegates. Its centre of gravity is what a control plane owns: tenancy, placement, trust boundaries, money, and the evidence that work was done.

## Adjacents

- **OpenHands, Cloud/Enterprise plus software-agent-sdk.** This is the hosted autonomous coding-agent platform with the most documented architecture: conversations on sandboxed runtimes, issue/PR resolvers, budgets. It overlaps placement, workspaces, intake, watch and money.
- **Temporal, as the substrate for an agent fleet.** This is the durable-execution adjacent. Pull-based workers on task queues, fairness keys, leases and retries, and payload codecs that keep keys with the customer. It overlaps placement and scheduling, failure semantics, intake (signals), and the wall (workers dial out).
- **GitHub Copilot cloud agent, formerly the coding agent.** This is the CI-driven runner. An issue or mention starts a session on an ephemeral Actions VM behind a firewall allowlist, and its PR comments feed back. It overlaps intake and feedback, workspaces and egress, trust, money and evidence.
- I considered Coder (Tasks, external provisioners that pull) and set it aside. It runs the agent's loop inside the workspace, which is the opposite of the property this spec is built on.

## Rubric

Frozen before scoring.

| # | Criterion | Measures | 10/10 looks like | Weight |
|---|---|---|---|---|
| C1 | Conceptual model and layering | How precise the core nouns are, and how cleanly the engine below, the platform, and a product above separate | Few orthogonal concepts, each owned by one layer; invariants stated once; upper layers extend without reaching into lower ones | 11 |
| C2 | Work, placement and scheduling | How sessions become work, where it runs, fair share, pinning, and routing to stateful hosts | One work model; placement first-class with wait and refusal semantics; fairness and tenant limits enforced at claim; explicit stateful routing | 11 |
| C3 | Failure semantics and recovery | Leases, fencing, idempotency, retry by effect, resume, mass outage, orphan cleanup | Everything leased and fenced; stale writers refused; side effects keyed and never unsafely repeated; one recovery mechanism; fleet-wide outage handling | 12 |
| C4 | Workspace isolation and egress | Isolation levels, how a level is guaranteed, credential stripping, egress control | Isolation pinned, verified by the executor, refused rather than downgraded; enforced egress allowlist; no platform credential reachable from the sandbox | 10 |
| C5 | Trust, identity and the tenant wall | Identity model, untrusted input, secret placement, connections across the wall, operator access, keys and retention | Distinct machine, principal, payer and actor; outside text never instructs; secrets resolved where they are used and never cross the wall; the customer side opens every connection; tenant-revocable keys with provable deletion | 11 |
| C6 | Cost, budgets and metering | Metering, scopes and windows, ledger, price source, fail-closed behaviour, rate vs spend | One ledger and one price source; holds before calls; scoped windows; fail closed when the payer is unknown; rate and spend kept separate; reconciled settlement | 8 |
| C7 | Intake and the feedback loop | Work from outside, routing back to the session, wake rules, bounds on automations | Signed events routed to the originating session; explicit wake rules; defined who may instruct; automations bounded by cost, rate, concurrency and hop limit | 9 |
| C8 | Evidence and verifiable outcomes | Execution records, provenance, protected validation, completion gate | Every execution recorded with version, environment and provenance; validation run apart from the agent on protected checks at the delivered version; one gate that refuses unvalidated success | 10 |
| C9 | Watching and steering | Live streams, late join, steering, takeover and hand-back | The durable record is the truth and the live view a cache; scoped reads; steering at defined points; takeover parks the agent and records human actions in the same record | 6 |
| C10 | Extensibility and contract clarity | How a product extends the platform; versioned wire types; typed APIs | Products extend through the registries the platform itself uses; versioned public types with floors; generated typed clients; no fork needed | 6 |
| C11 | Verifiability and operability | Mechanical enforcement of rules, twins, observability, operational burden | Rules enforced by gates and contract tests; deterministic twins; bounded-label telemetry; operating burden proportional to scope | 6 |
| | | | **Total** | **100** |

## Scores

| Criterion | Weight | distro_gentic | OpenHands | Temporal | Copilot cloud agent |
|---|---|---|---|---|---|
| C1 Conceptual model and layering | 11 | 7 | 6 | 6 | 6 |
| C2 Work, placement, scheduling | 11 | 7 | 3 | 8 | 4* |
| C3 Failure semantics | 12 | 8 | 4* | 8 | 3* |
| C4 Isolation and egress | 10 | 5 | 4 | 1 | 7 |
| C5 Trust, identity, wall | 11 | 8 | 4 | 5 | 7 |
| C6 Cost and budgets | 8 | 7 | 4 | 1 | 6 |
| C7 Intake and feedback | 9 | 8 | 5* | 4 | 6 |
| C8 Evidence | 10 | 7 | 3 | 4 | 5 |
| C9 Watching and steering | 6 | 7 | 7 | 6 | 7 |
| C10 Extensibility and contracts | 6 | 6 | 8 | 9 | 7 |
| C11 Verifiability and operability | 6 | 6 | 5 | 8 | 5* |
| **Weighted result** | **100** | **70** | **46** | **54** | **56** |

\* Low confidence: the system's documentation does not cover the criterion well enough.

The scopes differ.
- Temporal specifies nothing for C4 or C6. Its scores there measure that absence; they are not a penalty for being a different kind of system.
- OpenHands and Copilot own an agent loop, which distro_gentic delegates and no criterion measures.

## distro_gentic, criterion by criterion

`S/` means `scaffold/acme_root/`.

**C1, conceptual model and layering: 7.**
- **Spec strengths** (`distro_gentic_spec.md`):
  - The four planes in At a Glance.
  - "Sessions Are Work" collapses every kind of work into one queue with one shape.
  - The identity table in "Four Identities".
  - "A Workspace Is a Cache".
  - Each invariant is stated once in The Core, and each lens group is mapped to its home section (`lenses/README.md`).
  - The spec cites the engine and the guideline rather than restating them.
- **Where the code falls short of that:**
  - **The platform is a fork.** It edits 287 of the engine's 1,380 scaffold files (`git diff origin/scaffold HEAD`).
  - **The engine's copy imports the platform.** `S/om/src/acme/om/windows/impl/gate.py:31` imports `acme.om.projects`, which inverts the dependency.
  - **Platform modules reach into engine `impl` modules.** Examples: `billing/impl/gate.py:59-68` and `matrix/root.py:32-34`.
  - **"One ledger" has two in the code.** `root.py:891-903` wires the engine's `LedgerStorage` beside billing's `MoneyLedgerStorage`.
  - **"Gate" names four different things:** the budget, money, call, and result gates.

**C2, work, placement and scheduling: 7.**
- **What is specified and built:**
  - Kinds of work go onto per-environment lanes in one queue (`S/om/src/acme/om/placement/kinds.py:307-347`).
  - A host is handed work by its identity, never by what it asks for (`kinds.py:321-327`).
  - A pinned session waits visibly and moves only when a principal moves it (`hosts/impl/manager.py:273-324`).
  - A workspace's `exec` work goes to the host that holds it (`relay/impl/manager.py:339-351`).
  - The tenant concurrency guard runs at claim time with a delay and a refunded attempt, tested over Postgres (`session_runner/fair_share.py:28-31`, ADR 2002).
- **What held it back:**
  - Advertised capabilities are not used for routing. Prepares go to the pool lane, and an unfit host refuses with a 30s deferral.
  - Only one tier lane is deployed (`main.tf:540-566`).
  - Lost and offline hosts are not distinguished. Only revocation counts as lost, so a host that dies strands its sessions (`relay/impl/workspaces.py:38-45`).
  - The cloud host pool the spec describes is not deployed (ADR 2026).

**C3, failure semantics and recovery: 8.**
- **Strongest part of the design:**
  - The engine's writer epoch fences runner writes and relayed commands (`relay/impl/manager.py:760-771`, Postgres compare-and-set in `steps/storage/impl/postgres.py:153-169`).
  - `exec` items are keyed by the tool request and carry the tool's effect. An `unsafe` item has one attempt and completes `interrupted` (`relay/rules.py:264-304`, `manager.py:637-659`).
  - The outage signal is shared per provider and credential, and wake-ups are staggered (`agent_sessions/rules.py:277-299`).
  - The sweep carries named duties (spec, "Failure at Fleet Scale").
- **What held it back:**
  - **The item id is not stable across resume.** It includes an `occurrence` counter kept in a per-process LRU (`S/om/src/acme/om/relay/impl/transport.py:111,333-340`). A call resumed in the same runner process gets a new item id, which undermines "never starts a second one". The test hides this because it rebuilds the transport (`om/tests/unit/test_relay.py:300-334`).
  - **Gaps in fencing and keying:**
    - Relayed reads carry `epoch=None`.
    - Relayed file operations are keyed by `new_id()`.
    - Repeatable items exhaust 3 attempts and then sit queued.
  - **No defaults in the spec.** The spec hands lease lengths and similar values to "each system" (What This Spec Does Not Cover).

**C4, workspace isolation and egress: 5.**
- **The spec is excellent:**
  - "Pinned, Probed, Refused".
  - An isolation table that says what each level separates.
  - An egress allowlist naming destinations and methods.
- **What the code does well:**
  - Process environments are stripped of credentials (`infra/.../transports/local.py:98-103`, `container.py:28-38`).
  - A refusal parks the loop on `resource` before the first model call (`loop.py:302-317`).
  - Source control is reached through bundles the platform makes (ADR 2023), which is stronger than the spec.
- **What is missing or contradicts the spec:**
  - **No VM or microVM provider exists.**
  - **An allowlist session cannot run outside `local`.** The container provider accepts only `NONE` or `OPEN` egress (`S/infra/src/acme/infra/workspaces/container.py:156-161`), and `enforces_allowlist` is never set (`workspaces/types/host.py:24`).
  - **The host advertises modes it cannot run.** It advertises `vm` and `directory` from probes but has a transport only for containers (`apps/host/.../main.py:143-155`). That breaks the spec's own "advertises only what it probed" in spirit.
  - Internal network ranges are left "the host's to close" (`container.py:133-134`).

**C5, trust, identity and the tenant wall: 8.**
- **Built and real:**
  - `CallAudit` carries the four identities, with a validator that keeps them apart (`trust/types/identities.py:52-79`).
  - Each step carries an `Origin`, and outside text is quoted as `<data origin=…>` (`windows/rules.py:548-564`).
  - Hosts pull, hold an `hst_` credential that rotates at half-life, and enforce owner ceilings from a file the platform cannot raise (`apps/host/.../ceilings.py:83-202`, deviation DEL-01).
  - Cloud secrets and wall secrets are refused in each other's direction (`trust/rules.py:75-79`).
  - Opening session content needs its own operator grant (`trust/impl/operator.py:68-73`).
  - Content is sealed per session with AES-GCM, with a KMS backend available (`privacy/impl/sealed_steps.py`, `infra/keys/kms.py`).
- **What held it back:**
  - Secret brokering is a null implementation, and a secret's declared scope is never enforced.
  - Bring-your-own key service is plumbed but never wired (`root.py:783-786`). KMS defaults to one shared key.
  - Under KMS in production, key destruction is audited with `reported: False`. That falls short of "as the key service reported it".
  - Only tool-call audits carry all four identities, not "an audit entry".

**C6, cost, budgets and metering: 7.**
- **Built and real:**
  - The ledger is append-only, enforced by `REVOKE UPDATE, DELETE` (`om/migrations/sql/activity/202610032301_money_ledger.up.sql`).
  - Holds draw from buckets in a fixed order (`billing/types/ledger.py:34`), and limits count settled spend plus open holds (`budgets/rules.py:276-280`).
  - Spend fails closed with `SpenderUnknown` (`billing/rules.py:156-231`).
  - Rate parks (`PROVIDER`) and spend parks (`BUDGET`) are kept apart.
  - The matrix is versioned and a session keeps its pinned version (`matrix/storage/impl/postgres.py:54-78`). Eligibility filters fallbacks too.
- **What held it back:**
  - **The price table is a Python constant** (`budgets/impl/pricing.py:62`). A hold open across a price deploy settles at `price=None`, which becomes 0 units.
  - **Usage has two aggregations:** `ledger_counts` vs `usage_records`.
  - **The anomaly guard's park cannot be cleared in production.** It needs `approve_call`, which no route serves.
  - **Payments are not wired** (`PaymentProviderAbsentImpl`).

**C7, intake and the feedback loop: 8.**
- **Built and real:**
  - The spec's "Feedback Routing" table is implemented almost row for row (`intake/rules.py:73-99`).
  - A comment instructs only from a mapped user with a live membership who may instruct (`intake/impl/manager.py:267-301`).
  - A person's push hands the session over.
  - Automations require cost, rate and concurrency limits, admit under a row lock, ignore their own events, and stop at a hop limit (`automations/types/automation.py:129-151`, `rules.py:59-70`).
  - Playbook gates only narrow policy, and knowledge needs a person's review before any session recalls it.
- **What held it back:**
  - **A hop-limit hole.** The cause is looked up by the event's `session_id` (`automations/storage/impl/postgres.py:218-230`). Events caused by a sub-agent of the same tree count as hop 1, not as self-events.
  - Chat approvals have no caller.
  - The code forbids an automation from invoking a playbook, which the spec permits.

**C8, evidence and verifiable outcomes: 7.**
- **The spec is unmatched by any adjacent:**
  - protected checks
  - validation on a fresh executor
  - a baseline first
  - one-sided exact or Wilson bounds and sequential tests
  - provenance `real`/`twin`/`double`
  - one result gate
- **Much of that is real code:**
  - Clopper-Pearson, Wilson, and an optional-stopping test (`evidence/rates.py:18-71`).
  - The gate requires a clean tree at the head and only runs the validation's own executor wrote (`evidence/rules.py:243-323`).
  - A fresh executor per run, with protected files made read-only (`workspaces/impl/executor.py`).
- **Where the spec's promises go unenforced:**
  - **Promise 1 is broken.** The agent's own `run_command` writes no execution record (`platform_agents/tools.py:414-434`; `record_run` has no production caller).
  - **Promise 2 is a prompt, not a rule.** A baseline is asked for in the agent's prompt only (`platform_agents/kinds.py:101,138`).
  - Hypotheses have no writer.
  - Answer-rule kinds complete without the gate (`loop.py:716-718`).
  - Matrix qualification is an operator's `passed: bool` (`matrix/types/record.py:34-44`), not a linked benchmark record.

**C9, watching and steering: 7.**
- **Built and real:**
  - The realtime channel carries hints, and content is a live read through an HMAC-signed, 5-minute, session-scoped handle (ADR 2007, `watch/impl/manager.py:97-112`).
  - Each open stream has a bounded buffer that drops the oldest part.
  - Taking control parks the loop on a hand-over. Giving back turns the summary into a message plus an `environment_changed` step (`loop.py:1363-1399`).
  - A person's commands are audited `exec` work, and the host owner must opt in (`watch/impl/manager.py:199-243`).
- **What held it back:**
  - The spec's recorded terminal is one-shot commands in the code.
  - Video segments and the read of an artifact's bytes so far are absent.
  - Mirrors, an optional part of the spec, do not exist.

**C10, extensibility and contract clarity: 6.**
- **Built and real:**
  - A product adds kinds through the same registries the platform uses, and duplicate names are refused (ADR 2025).
  - `exec` has `WIRE_VERSION` and `WIRE_FLOOR` (`hosts/rules.py:25-31`).
  - The OpenAPI schema generates the TypeScript and Python clients, and CI fails on drift (`.github/workflows/ci.yml:50`).
  - The claimant kit is a shared half of every claimant (`clients/python/src/acme/client/claimant/`).
- **What held it back:**
  - **Products adopt by copy and merge**, three layers deep (`scaffold/new.py`, ADR 2001). The scaffolding skills tell a product to edit 4 to 8 base files each, and every edit is a future merge conflict.
  - **The claimant API has no wire version**, and its `payload` is `dict[str, Any]` (`services/api/types/claimants.py:80`).
  - OpenAPI `info.version` is still `0.1.0`.
  - Pyright runs in `standard` mode, not `strict`.

**C11, verifiability and operability: 6.**
- **Strengths:**
  - About 3,467 Python and 575 TypeScript tests.
  - 57 storage contract modules run against both the memory and Postgres implementations.
  - Twins are refused outside `local`, and a scripted model provider exists.
  - Dashboard labels are bounded (`infra/observability.py:95-117`).
  - Operational tasks are skills under `.agents/skills`.
- **What held it back:**
  - **Almost no lens is enforced by a program.** 104 of 107 are review-only, and `distro-check` decides three partially (PLC-10, PLC-16, FLT-12). The rest is LLM review.
  - **The spec and code have drifted** in places the gates cannot see:
    - "hosts by pool" is a gauge labelled by `state` (`observability.py:105`);
    - "purged" is "released" in code;
    - "every cloud worker runs the sweep" is a recovery-only sweep in the runner.
  - `benchmark/` scores how chat assistants perceive the repository. It is not a system benchmark.

## Where it differs

- **Stronger: effect-typed relayed side effects.**
  - An `exec` item carries `read_only`, `idempotent` or `unsafe`, and the sweep requeues by effect.
  - Temporal gives at-least-once activities and leaves idempotency to you.
  - This buys a defined outcome (`interrupted`, outcome unknown) for a crashed shell command, with no guessing.
- **Stronger: a completion gate tied to evidence.**
  - Success requires validation at the delivered head, on an executor apart from the agent, with protected checks.
  - Copilot runs scanners and OpenHands offers an opt-in critic. Neither refuses a success.
- **Stronger: hosts pull, under the owner's ceilings.**
  - A customer-side host can never be widened by a compromised control plane (DEL-01).
  - Temporal's workers pull but hold no ceilings. OpenHands self-hosting needs inbound webhooks.
- **Stronger: identities and money.**
  - Executor, principal, spender and actor are separate, and spend fails closed against one ledger.
  - The adjacents conflate payer with org or user, or omit spend entirely (Temporal).
- **Weaker: enforced egress and real isolation tiers.**
  - Copilot ships an ephemeral VM per session and a default firewall allowlist.
  - distro_gentic specifies more but enforces only none-or-open egress, on containers.
- **Weaker: proven durability machinery.**
  - Temporal's event history, replay and timeouts are fully specified with defaults.
  - distro_gentic's keyed-item identity is process-local, and it leaves lease values unspecified.
- **Weaker: contracts and distribution.**
  - Temporal and OpenHands ship versioned SDKs and typed protocols.
  - distro_gentic ships a scaffold to copy and merge, with one versioned wire type.
- **Broader:** it owns money, the model matrix, retention and keys, evidence statistics, and the platform assistant. Temporal leaves all of these to the application; Copilot and OpenHands keep them inside their own products.
- **Narrower:** it owns no agent loop, no IDE or terminal UI, and no sandbox runtime of its own. OpenHands and Copilot ship those.
- **Different: where the brain runs.**
  - distro_gentic keeps the loop and model keys in the cloud and relays tool calls into the customer's network.
  - Copilot and OpenHands run the agent inside the sandbox.
  - The cloud brain wins when keys, budgets and history must never leave the platform. The in-sandbox brain wins on latency and simplicity when the sandbox is the platform's own.
- **Different: copy versus depend.**
  - Copy-and-merge lets a product change anything and see everything.
  - A dependency on an SDK or engine makes upgrades cheap.
  - The first wins while the platform is being shaped; the second wins once many products sit on it.

## What I would change

1. **Derive each `exec` item id from durable step state, not a per-process counter** (`relay/impl/transport.py:333-340`). Key relayed file operations and fence reads the same way. Moves C3 by about 1.
2. **Make the spec's egress and isolation true or remove the claims.**
   - Ship an enforcing egress proxy for containers and set `enforces_allowlist`.
   - Stop the host advertising `vm` and `directory` until providers for them exist.
   - Otherwise, label the VM and allowlist rows of the spec as unimplemented in this scaffold.
   - Moves C4 by 2 to 3.
3. **Record every execution, the agent's included, and make the result gate require a recorded baseline.** Do this in `RunCommandImpl` and `evidence/rules.py`, so promises 1 and 2 are enforced rather than prompted. Moves C8 by 1 to 2.
4. **Pick one ledger.** Remove the engine's `LedgerStorage` wiring from `root.py:891-903`. Version the price table in storage, not in a Python constant. Moves C6 and C1 by about 1 each.
5. **Turn high-severity lenses into `distro-check` rules or contract tests.** Start with PLC-14, PLC-18, PLC-20, EVD-10 and MNY-11. Add a gate that holds the spec's signal names, such as "hosts by pool", to the dashboard. Moves C11 by 1 to 2.
6. **Remove the engine copy's import of the platform** (`windows/impl/gate.py:31`). Expose seams instead of reaching into `impl` modules, and cut the base-file edits the scaffolding skills require. Moves C1 and C10 by about 1.
7. **Specify lost versus offline hosts** with a liveness-based loss rule and a bounded wait. Also specify who serves each tier lane. Moves C2 by about 1.
8. **Put a wire version and a typed payload on the claimant API**, and bump the OpenAPI version. Moves C10 by about 0.5.
9. **Close the automation hop-limit hole** by attributing causes to the session tree. Wire chat approvals and `approve_call`. Moves C7 and C6 by about 0.5 each.

## Method

- **distro_gentic**, commit `a8428906b86a`, tag v0.10.0 (2026-10-07), on engine v0.9.0 and guideline v0.52.2:
  - I read in full: the spec, README, AGENTS.md, CHANGELOG, lens README and `lenses/placement.md`.
  - I read every other lens at the level of title, severity and check.
  - Four parallel audits compared the scaffold's code, ADRs 2001–2046 and tests against every lens group, with file and line evidence.
  - I re-checked the key findings by hand: the occurrence counter, container egress modes, the hosts gauge, the engine gate's import, the PLC-10 exceptions, and `enforces_allowlist`.
  - I measured the platform's diff against `origin/scaffold`.
- **OpenHands:**
  - docs.openhands.dev, undated, read 2026-10-07.
  - OpenHands v1.24.0 (2026-09-25); software-agent-sdk around v1.46 (the release pages conflict).
  - arXiv:2511.03690 (Nov 2025).
  - C2, C3 and C7 rest on thin evidence: the scheduler, crash handling of an in-flight tool call, and PR follow-up continuity are undocumented.
- **Temporal:**
  - docs.temporal.io, undated, read 2026-10-07.
  - Server v1.32.0 (2026-09-11).
  - The Replay 2026 announcements (2026-05-06) and the OpenAI Agents SDK integration (GA per Replay 2026).
  - Evidence is solid. Workflow-task fencing is not in the user documentation, so C3 does not rely on it.
- **Copilot cloud agent:**
  - docs.github.com, undated, read 2026-10-07.
  - The GitHub changelog for the rename (2026-04-01), runner controls (2026-04-03), secrets (2026-05-11), usage billing (2026-06-01) and session streaming (2026-07-02).
  - C2, C3 and C11 rest on thin evidence: scheduling, resume and internals are undocumented.
- **Confidence in the distro_gentic scores:** C3, C4, C6 and C8 rest on code read line by line. C1 and C10 rest on the diff measurements and the ADRs. Of the scaffold's 134k added lines, I did not read every line.