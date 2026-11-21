---
name: distro-scaffold-agent-kind
description: "Add an agent kind the platform ships, or a new version of one: a folder of its own with a profile over the engine's one loop (its tools, done rule, authority, workspace, policy layer, and model roles), each version's prompt in Markdown pinned by digest, and any manuals and wiki entries it ships for its sessions, in the shipped catalog every process builds from, with any tool of its own and its tests, in the shape of the platform's shipped agents. Python."
allowed-tools: Read, Grep, Glob, Write, Edit, Bash(make check), Bash(uv run:*), Bash(git status:*), Bash(git show:*)
---

# distro-scaffold-agent-kind

A path that starts with `../` is read from this skill's folder as
`realpath` resolves it.
Conventions: `../_shared/scaffold-conventions.md`.
Sections of `../../distro_gentic_spec.md`: The Agents a Platform Ships,
Agent Session Runners, Workspaces and Isolation (Isolation Levels), Models Are
an Agent Fleet Decision.
Lenses: `../../lenses/agent-fleet.md`, and `../../lenses/placement.md`
for where a kind lives.

## Input

`<kind> [--done answer|result_tool] [--tools <tool,...>] [--authority delegated|steady] [--started-by person|agent|both] [--share <micros>] [--workspace none|container] [--classes <class,...>] [--roles <role,...>] [--asks <role>=<size>,...]`,
and what the kind's agent does and may never do, in the arguments or
in the conversation. That text is the kind's prompt (step 2). Any
operation manual the kind ships for its sessions, and anything its
sessions should not have to rediscover, with the words that should
bring it in, may come in the conversation too: its manuals and its
wiki (step 6).

Example: `triage --done answer --tools list_agent_sessions,read_agent_session --authority steady --workspace none --classes read`,
for "reads a failed session and the sessions beside it, changes
nothing, and answers which session should take it".

- `<kind>` is the kind's name, snake case, as `AgentKind.name` holds it,
  and its folder's name. `<KIND>` is its name constant in upper snake
  case, and `<KIND>_KIND` the profile of its latest version.
- `--done`: `answer` for an agent whose turn with no tool call is its
  answer; `result_tool` for one that delivers work, which only its
  result tool ends, as the software engineer's `submit_result` does.
- `--authority`: `delegated` runs each call under the asking person's
  live permissions; `steady` under one principal fixed when the session
  is made. Unattended, an agent a person talks to is `delegated`, and
  one that works on its own is `steady`. A kind a spawn starts is
  `steady`, even when a person starts it too, as analysis and the
  reviewer are.
- `--started-by`: who may start a session of the kind, as
  `AgentKind.started_by` holds it; every shipped version states it.
  `person`, the default, sets `BY_A_PERSON`: a person starts the kind,
  or a hand-off reaches it, and a spawn of it is refused. `agent` sets
  `frozenset({Starter.AGENT})`, for a kind only a spawn starts: a
  person's start of it is refused. `both` sets `SPAWNED`, for a kind a
  person starts and a lead or another kind spawns. `BY_A_PERSON` and
  `SPAWNED` are in `om/src/<name>/om/platform_agents/kinds/__init__.py`. A kind a spawn starts, `agent` or `both`, names
  its share beside it, as the reviewer names `REVIEWER_SHARE`, and its
  parent holds what the spawn asks of it (step 4). When it is not
  given, a kind given `--share`, or one the arguments or the
  conversation say a spawn starts, is `both`, and any other is `person`.
- `--share`: what one session of the kind may spend over its life as a
  sub-agent, in reference cost, `<KIND>_SHARE = Amount(cost_micros=<micros>)`
  beside the kind. A kind a person alone starts names none. When it is
  not given for a kind a spawn starts, it is the kind's loops at its
  step guard over a cached window, as `ANALYSIS_SHARE` is:
  `<KIND>_LOOPS = 2` (its first loop, and one more a follow-up asks
  for), times its step guard (`Limits().step_guard`, the engine's,
  unless the kind sets its own), times `CACHED_CALL_MICROS`, and times
  `XL_CALL_FACTOR` when it asks XL of `MAIN`, as `REVIEWER_SHARE` does
  in `kinds/reviewer/kind.py`. `<KIND>_LOOPS` and `<KIND>_SHARE` go in
  the kind's `kind.py`; the two factors are in `kinds/__init__.py`.
- `--workspace`: `container` for a kind that reads or changes files or
  runs commands (the profile's `isolation` is `WORKSPACE`), `none` for
  one that has no workspace (`NO_AGENT_WORKSPACE`). A delegated kind a
  person talks to has none, as the assistant has none.
- `--classes`: the tool classes its policy layer allows, `allowing(...)`.
- `--roles`: model roles beyond `MAIN` the kind's calls take.
- `--asks`: the model size the kind asks of a role, as `main=xl`. By
  default a kind asks what every shipped kind but the reviewer asks,
  `ASKS` in `kinds/__init__.py`: L of `MAIN` and S of `SUMMARIZER`. A size named
  here replaces that role's ask, as the reviewer's `REVIEWER_ASKS` asks
  XL of `MAIN`, and a role of `--roles` asks nothing unless it is named.

## Created

A kind is a folder of its own, `om/src/<name>/om/platform_agents/kinds/<kind>/`,
beside the others and never inside one. The shape is
`kinds/reviewer/` for a kind with one version and
`kinds/software_engineer/` for one with several, over `AgentKind` in
`om/src/<name>/om/agents/types/kind.py` and the folder's rules in
`om/src/<name>/om/agents/prompts.py` and
`om/src/<name>/om/platform_agents/folders.py`.

| File | Holds |
|------|-------|
| `kinds/<kind>/__init__.py` | its docstring alone: the kind's name, its versions in `kind.py`, their prompts in `prompts/` |
| `kinds/<kind>/kind.py` | a docstring of what the kind does; a constant per version, `<KIND>_V<N>` for each but the latest, which is `<KIND>_KIND`, each with `prompts=(prompt_of(__file__, <N>),)` and its `started_by`; any `<KIND>_LOOPS` and `<KIND>_SHARE`; and `VERSIONS`, every version the platform still runs, oldest first |
| `kinds/<kind>/prompts/v1.md` | the prompt of version 1, Markdown, ending in one line break (step 2) |
| `kinds/<kind>/prompts/lock.json` | `{"v1.md": "<digest>"}`, the digest step 7 prints |
| `kinds/<kind>/manuals/<name>.md`, `kinds/<kind>/wiki/<slug>.md` (step 6) | each manual and each entry the kind ships for its sessions |

and, when the kind calls a tool the tree does not have, the tool's test
module, as step 3 says.

## Changed

| File | Change |
|------|--------|
| `om/src/<name>/om/platform_agents/kinds/__init__.py` | `<KIND>`, any tool name constant it adds, and its line in the module docstring; and each new version whose workspace starts from its agent project's workspace base, by its name and version, in `WORKSPACE_BASE_KINDS` (step 2) |
| `om/src/<name>/om/platform_agents/shipped.py` | the kind's module imported, `from <name>.om.platform_agents.kinds.<kind> import kind as <kind>`, and named in `FOLDERS`, after the platform's others, so `SHIPPED` holds its versions |
| `om/src/<name>/om/platform_agents/kinds/<parent>/kind.py` and its `prompts/` (a kind a spawn starts, whose parent lacks what step 4 says) | the parent's next version, holding the kind's tools and any paragraph of its prompt step 4 asks for, beside its last in `VERSIONS`, with its prompt file and its lock entry, and in `WORKSPACE_BASE_KINDS` when its last version is (step 2); the tests below take that version as they take the kind's |
| `om/src/<name>/om/platform_agents/tools/<toolset>.py` (a tool of its own) | `<Tool>Impl(NativeToolImpl)`, its input, and its output, in the module of its toolset |
| `om/src/<name>/om/platform_agents/catalog.py` (a tool of its own) | the tool in `with_shipped`, in `own_specs` and in `own` |
| `om/tests/unit/test_platform_agents.py` | the kind in `test_every_shipped_agent_is_a_profile_that_sets_its_powers`, the cases of step 5, each of its versions in `NAMED_ONE_BY_ONE` with the tools it names one by one, since `test_each_shipped_kind_built_from_toolsets_renders_the_tool_block_it_named_one_by_one` holds that set equal to `SHIPPED`, and its latest version in `RENDERED`, the digest of its request's tools, with its profile in the loop of `test_each_shipped_kind_renders_its_versions_bytes_with_a_break_after_its_prompt`. That test renders each kind's latest version alone, so a parent's next version takes its last version's entry, and it stops at the first kind whose entry is missing or differs: give each new entry a placeholder digest, `"pending"`, run the test with `-vv`, since a shorter report cuts the digest short, pin the digest its failure prints, and run it again until it passes |
| `om/tests/unit/test_kind_folders.py` | each new version in `SETTINGS`, the digest of its settings, the kind's and a parent's next version alike; a released version's entry never changes: run `test_each_shipped_version_keeps_the_settings_it_was_released_with` once with `-vv`, and pin the digest its failure prints for each new version |
| `om/tests/unit/test_platform_agents.py` (a kind a spawn starts) | its name in `SPAWNED_KINDS`, and its profile and its share in the list of kinds that name one in `test_every_shipped_kind_a_spawn_can_start_names_a_share`, which holds every other latest version to name none |
| `om/tests/unit/test_matrix.py` (with `--roles`) | the case of step 5 for its roles |
| `om/tests/contracts/matrix.py` (with `--roles`) | `CATCH_ALL` and the default roles of `publish` serve the kind's roles, since a role added to a shipped kind joins the required set of every version, and the unit and integration matrix suites refuse a default publish that lacks it |
| `om/tests/contracts/matrix.py`, `om/tests/unit/test_matrix.py`, and `services/api/tests/test_matrix_api.py` (a model size no shipped kind asked before) | `SIZED` holds a row for the size, since a version is published only with a row for each size a shipped kind asks; in `test_matrix.py`, the roles zipped strictly with `SIZED` take the role the size is asked of, and the set of the sizes the shipped kinds ask takes the pair; in `test_matrix_api.py`, the list of the sizes a published version's rows match takes the size |
| `om/src/<name>/om/platform_agents/rules.py` (a kind that may only read, or read and hand on) | its reach in `REACHES`, as step 4 says |
| `om/src/<name>/om/platform_agents/README.md` | the kind, in What it holds |
| `om/README.md`, `llms.txt` | the count and the list of the kinds the platform ships |

## Procedure

1. Every process builds its catalog from `SHIPPED`:
   `build_platform_managers` in `om/src/<name>/om/platform_root.py`
   puts it before the product's own kinds, and the model matrix's root,
   `om/src/<name>/om/matrix/root.py`, requires every role a shipped kind
   names. A kind in `SHIPPED` is in every process, so no container
   changes. A product's own kind, one no other product built on the
   platform would ship, is the engine's: `agentic-scaffold-agent-kind`,
   with its wiring changed in this base. From that skill a product
   still writes the kind's folder, `om/src/<name>/om/agents/kinds/<kind>/`
   (its `__init__.py`, its `kind.py` with each version and `VERSIONS`,
   and each version's prompt in `prompts/` with its entry in
   `prompts/lock.json`), its tools, and its bounds (its steps 2 to 4),
   `om/tests/unit/test_agent_kinds.py` with the catalog cases of its
   step 5, read over `PRODUCT_KINDS.agent_kinds`, and the kind in
   `om/src/<name>/om/agents/README.md`; its manuals and its wiki go in
   its folder as step 6 says. It writes none of that skill's wiring: no
   `AGENT_KINDS` (`om/src/<name>/om/agents/kinds/__init__.py` holds a
   docstring alone); no check of its own that `prompt_breaches` finds
   nothing, since the base's `om/tests/unit/test_kind_folders.py` runs
   `folder_breaches`, the engine's check and the platform's, over every
   folder in `om/src/<name>/om/agents/kinds/`, and holds each one
   declared; no `agent_kinds=` in a container's call to
   `build_platform_managers`, which stands here for that skill's
   `build_managers`; and neither the API's nor the maintenance worker's
   container test that reads that call. Each of its kinds goes in
   `PRODUCT_KINDS`, in `om/src/<name>/om/product_kinds.py`, as its
   folder: `folders=(folder_of(<kind>),)`, with
   `from <name>.om.agents.kinds.<kind> import kind as <kind>` and
   `from <name>.om.platform_agents.folders import folder_of`. Never put
   a folder's versions in `agents`, which holds a kind with no folder
   and would lose the folder's manuals and wiki. Its tools and the
   classes they declare go in `tools`, `classes`, and `ceilings` of
   `ProductKinds`, in `om/src/<name>/om/platform_root.py`, and every
   process's entry point hands `PRODUCT_KINDS` to its root as
   `PlatformPorts.kinds`.
   A version of its kind whose workspace starts from its agent project's
   workspace base, as the platform's software engineer does from version
   8, is named by its name and version in `workspace_bases`.
   A class of the product's that must always wait for a person takes its
   ceiling in `ceilings`, never a row in `DEFAULT_CEILINGS` in the
   platform's `tools/rules.py`, whatever the engine's
   `agentic-scaffold-tool` says for a class. Its container
   test holds instead that the kind declared in `PRODUCT_KINDS.folders`
   reaches each container's `build`, shape
   `workers/agent_session_runner/tests/test_product_parts.py`: the API's
   container starts a session of it, the session runner runs it, and
   the maintenance worker knows it.
   `tools` takes the managers late, as a callable, and returns the
   product's tools, each reading a manager when it is called, as
   `with_shipped` builds the platform's. The shape to copy is the tool in
   `om/tests/contracts/product.py`, `ReadTitleImpl`, which
   `ledger_product`'s `tools` builds over the late-bound managers.
   `tools` is handed the managers alone, and no integrations root
   reaches `PRODUCT_KINDS.tools`. So a tool that calls an outside system
   takes its client from the integrations the product builds at its
   root: the closure that is `tools` holds the client and passes it to
   the tool, as `ledger_product`'s `tools` passes `read`.
2. A kind is versioned, and a session keeps the version it started on.
   A version's prompt is what the arguments or the conversation say the
   kind does and answers, written as Markdown in `prompts/v<N>.md`: one
   text, ending in one line break. It never says how policy treats the
   kind (step 4). Its constant reads it, `prompt_of(__file__, <N>)`, and
   no prompt is a string in code. A change to a kind that the last
   commit holds
   (`git show HEAD:om/src/<name>/om/platform_agents/kinds/<kind>/kind.py`,
   and its `prompts/`) is the next version: a constant of its own beside
   the last in `VERSIONS`, its whole prompt in its own
   `prompts/v<N+1>.md`, even when it repeats the last one's and adds a
   paragraph, and its own lock entry (step 7). The last version's prompt
   file and lock entry never change, and both versions stay in
   `VERSIONS` while a session may run the last. A kind only this work
   wrote changes in place, its prompt file and its lock entry with it.
   Who may start a released kind is no exception: `SETTINGS`, in
   `om/tests/unit/test_kind_folders.py`, holds every field a version
   sets but its prompt, `started_by` among them, and a released
   version's entry there never changes, so a kind whose starters change
   takes its next version, and `SETTINGS` gains that version's digest.
   A next version of a kind whose last version is in
   `WORKSPACE_BASE_KINDS` (`kinds/__init__.py`) joins it, by its name
   and version: the workspaces manager looks a session's kind up there
   to start its workspace from its agent project's workspace base, and
   the gate passes with a version left out.
3. A kind names its tools by name and holds no more power than they and
   its policy layer give. `--tools` names tools, and the profile takes
   them two ways. A toolset of the platform's (`TOOLSETS` in
   `kinds/__init__.py`) whose every tool the kind may call goes in its
   `toolsets`, as the reviewer takes `AGENT_KNOWLEDGE_TOOLSET` for
   `search_agent_knowledge` and `read_agent_knowledge`. A tool whose
   toolset the kind does not take whole, and a tool of its own, go in
   its `tools` alone, each by its constant, as the reviewer names
   `COMMENT`. A kind that calls tools also takes `TOOL_OUTPUTS_TOOLSET`,
   whether or not `--tools` names `read_tool_output`: a result too long
   for its window, or one elided once read, is kept outside it under a
   notice that names that tool. The latest software engineer, analysis,
   reviewer, and ops analyst hold it.
   A tool the platform ships for it is a `NativeToolImpl` in the module
   of its toolset under `tools/`, or of the toolset it is closest to
   when it is in none, shape `ReadSessionImpl` (`tools/records.py`) for
   a read and `HandOffToSoftwareEngineerImpl` (`tools/handoff.py`) for a
   spawn, registered in `with_shipped`. Closest is by what the tool
   reads or changes, never by which tool wrote it: a reader of the
   tenant's records (its sessions and what each holds, what they wait
   on, its agent projects, its agent automations) goes in
   `tools/records.py`, even of the validation runs `validate` writes; a
   reader of a workspace's files in `tools/files.py`; of a pull request
   in `tools/review.py`; of hosts and spend in `tools/operations.py`.
   The new tool joins no toolset, so the kind names it alone.
   The engine's `agentic-scaffold-tool` holds what a tool's reach, spec,
   target, preflight, and failures must be, and its test's cases: follow
   its steps 1 to 6 where it is installed, and the shapes in `tools/`
   either way. Of its step 6's cases, the outward one is for an outward
   call alone, and the crash one for an `idempotent` or `unsafe` effect
   alone. This skill's paths stand in for its tables: the tool goes in
   `tools/<toolset>.py`, never `tools/native/`, and its test in
   `om/tests/unit/test_platform_tools_<toolset>.py`, made when its
   toolset has none yet, never `test_tool_<tool>.py`. This skill's
   steps stand in for its steps 7 and 8: the kinds name the tool as
   above, and a product's class takes its ceiling in
   `PRODUCT_KINDS.ceilings` (step 1).
   A `result_tool` kind names its result tool among its tools.
4. The profile sets its powers: `isolation` is `WORKSPACE` or
   `NO_AGENT_WORKSPACE`, and its `policy` is `allowing(...)` the classes
   it needs and no more. A kind that may only read, or read and hand on,
   is held to it at boot by its reach: the classes it may make, its
   authority, and no workspace, in `REACHES` in `rules.py`, which
   `refuse_reach` in `catalog.py` checks for every version of it over
   the whole catalog. A new kind a person talks to that acts on nothing
   takes a reach of its own, shape `kinds.OPS_ANALYST`. Its prompt says
   what it does and what it answers, never how policy treats it.
   A kind a spawn starts has a parent, the kind the arguments or the
   conversation say spawns it, and the parent holds what the spawn asks
   of it: the kind's tools among its own, since a child's tools are cut
   to its parent's (a lead, in `platform_agents/README.md`); the
   `sub_agents` toolset, a paragraph of its prompt on sub-agents, and
   `SPAWN` in its policy, as `ANALYSIS_V3` took them (the paragraph is
   the second of `kinds/analysis/prompts/v3.md`), when it lacks them;
   and, when its prompt must say when to start the kind, a paragraph
   that says it.
   A parent that lacks any of them gets its next version holding them,
   as step 2 says: with its own prompt file, lock entry, and `SETTINGS`
   entry, and in `WORKSPACE_BASE_KINDS` when its last version is, as
   the software engineer's is. Ask for that version; unattended, write it and name
   it in the output. When no shipped kind is named its parent, none
   changes: a product's lead starts it, as one starts the reviewer.
5. The tests hold, over `SHIPPED`, with the helpers of
   `om/tests/contracts/platform_agents.py` (`platform_over`,
   `Platform.start`, `calls`). An `agent` kind, whose start by a person
   is refused, is started in each by a lead's spawn, shape
   `test_a_lead_spawns_the_reviewer_under_its_share`, and
   `test_a_spawn_starts_each_shipped_kind_a_lead_starts_and_refuses_the_rest`
   reads `{Starter.AGENT}` as its `started_by`:
   - the kind is a profile that sets its powers: its tools, its done
     rule, its authority, its isolation, and its classes, in the shape of
     `test_every_shipped_agent_is_a_profile_that_sets_its_powers`, whose
     list of names and set of delivering kinds take the new kind;
   - it ends as its done rule says, over the scripted provider, shape
     `test_analysis_the_planner_and_the_assistant_end_by_their_answer`
     or
     `test_the_software_engineers_success_needs_a_passing_validation_at_its_head`;
   - a call past its policy layer is refused, shape
     `test_a_call_from_the_assistant_to_a_workspace_or_a_shell_is_refused`;
   - with `--roles`, a matrix version that serves not every role the
     kind calls is refused, shape
     `test_a_version_that_serves_not_every_role_its_kinds_call_is_refused`
     in `om/tests/unit/test_matrix.py`.

6. A kind may ship texts for its sessions beside its prompts, when the
   arguments or the conversation give them; with none given, it ships
   none, and its folder is whole without `manuals/` and `wiki/`.
   - An operation manual goes in `manuals/<name>.md`, `<name>`
     lowercase words joined by hyphens, its text whole. Each new session
     of the kind holds the kind's manuals first in its standing text, in
     name order, before the kind manual its tenant pins. Together they
     hold at most `MAX_MANUALS` characters (`folders.py`). A manual is
     no prompt: what every version must say goes in the prompt, which a
     version pins; a manual changes in place, and a session keeps the
     one it was made with.
   - What a session should not have to rediscover goes in
     `wiki/<slug>.md`, `<slug>` lowercase words joined by hyphens: a
     header between two `---` lines, `title: <one line>` and
     `trigger: <word>, <word>`, then a blank line and the text, at most
     `MAX_TEXT` characters. A session recalls the entry only when every
     word of its trigger appears in what it is about, each word of a
     phrase included: `flaky, check` recalls a session about a flaky
     check, and not one about a flaky test. The field has no way to say
     either word: words that are alternatives, as `flaky` and
     `intermittent` are, each take an entry of their own, under a slug
     of its own, with that one word as its trigger. Its sessions read
     it by `<kind>/<slug>`, and a session of another kind never reaches
     it.
   - Neither names a tool the kind's latest version does not hold, nor
     says to retry with no bound: the lever checks read both, and a
     finding fails the gate.
7. Pin each new prompt, and check every text: run
   `uv run pytest om/tests/unit/test_kind_folders.py -k every_kind_folder -vv`.
   Its failure names each breach by its file. For a new version it
   reads `prompts/v<N>.md: lock.json pins no digest for it; once its
   text is final, pin "v<N>.md": "<digest>"`: add that pair to the
   folder's `prompts/lock.json`, an object of file names to digests. A
   breach in a manual or an entry is fixed in its text. Run it again
   until it passes.

Then the gate, `make check`, as After writing in the conventions
runs it.

## Output

As `../_shared/scaffold-conventions.md` states.
