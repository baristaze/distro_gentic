---
name: distro-scaffold-agent-kind
description: "Add an agent kind the platform ships, or a new version of one: a profile over the engine's one loop with its tools, done rule, authority, workspace, policy layer, and model roles, in the shipped catalog every process builds from, with any tool of its own and its tests, in the shape of the platform's shipped agents. Python."
allowed-tools: Read, Grep, Glob, Write, Edit, Bash(make check), Bash(uv run:*), Bash(git status:*), Bash(git show:*)
---

# distro-scaffold-agent-kind

A path that starts with `../` is read from this skill's folder as
`realpath` resolves it.
Conventions: `../_shared/scaffold-conventions.md`.
Sections of `../../distro_gentic_spec.md`: The Agents a Platform Ships,
Session Runners, Workspaces and Isolation (Isolation Levels), Models Are
a Fleet Decision.
Lenses: `../../lenses/fleet.md`, and `../../lenses/placement.md` for
where a kind lives.

## Input

`<kind> [--done answer|result_tool] [--tools <tool,...>] [--authority delegated|steady] [--workspace none|container] [--classes <class,...>] [--roles <role,...>]`,
and what the kind's agent does and may never do, in the arguments or
in the conversation.

Example: `triage --done answer --tools read_file,list_files,read_session --authority steady --workspace container --classes read`,
for "reads a failed run's logs in its workspace and answers which
session should take it".

- `<kind>` is the kind's name, snake case, as `AgentKind.name` holds it.
  `<KIND>` is its name constant in upper snake case, and `<KIND>_KIND`
  the profile.
- `--done`: `answer` for an agent whose turn with no tool call is its
  answer; `result_tool` for one that delivers work, which only its
  result tool ends, as the engineer's `submit_result` does.
- `--authority`: `delegated` runs each call under the asking person's
  live permissions; `steady` under one principal fixed when the session
  is made. Unattended, an agent a person talks to is `delegated`, and
  one that works on its own is `steady`.
- `--workspace`: `container` for a kind that reads or changes files or
  runs commands (the profile's `isolation` is `WORKSPACE`), `none` for
  one that has no workspace (`NO_WORKSPACE`). A delegated kind a person
  talks to has none, as the assistant has none.
- `--classes`: the tool classes its policy layer allows, `allowing(...)`.
- `--roles`: model roles beyond `MAIN` the kind's calls take.

## Created

None, unless the kind calls a tool the tree does not have: then the
tool's test module, as step 3 says.

## Changed

The shape of a kind is the four profiles in
`om/src/<name>/om/platform_agents/kinds.py`, over `AgentKind` in
`om/src/<name>/om/agents/types/kind.py`.

| File | Change |
|------|--------|
| `om/src/<name>/om/platform_agents/kinds.py` | `<KIND>`, any tool name constant it adds, `<KIND>_KIND`, its place in `SHIPPED`, and its line in the module docstring |
| `om/src/<name>/om/platform_agents/tools.py` (a tool of its own) | `<Tool>Impl(NativeToolImpl)`, its input, and its output |
| `om/src/<name>/om/platform_agents/catalog.py` (a tool of its own) | the tool in `with_shipped`, in `own_specs` and in `own` |
| `om/tests/unit/test_platform_agents.py` | the kind in `test_every_shipped_agent_is_a_profile_that_sets_its_powers`, and the cases of step 5 |
| `om/tests/unit/test_matrix.py` (with `--roles`) | the case of step 5 for its roles |
| `om/tests/contracts/matrix.py` (with `--roles`) | `CATCH_ALL` and the default roles of `publish` serve the kind's roles, since a role added to a shipped kind joins the required set of every version, and the unit and integration matrix suites refuse a default publish that lacks it |
| `om/src/<name>/om/platform_agents/README.md` | the kind, in What it holds |
| `om/README.md`, `llms.txt` | the count and the list of the kinds the platform ships |

## Procedure

1. Every process builds its catalog from `SHIPPED`:
   `build_managers` in `om/src/<name>/om/root.py` puts it before the
   product's own kinds, and the model matrix's root,
   `om/src/<name>/om/matrix/root.py`, requires every role a shipped kind
   names. A kind in `SHIPPED` is in every process, so no container
   changes. A product's own kind, one no other product built on the
   platform would ship, is the engine's: `agentic-scaffold-agent-kind`,
   with its wiring changed in this base. From that skill a product
   still writes the kind's versions, its tools, and its bounds (its
   steps 2 to 4), `om/tests/unit/test_agent_kinds.py` with the catalog
   cases of its step 5, read over `PRODUCT_KINDS.agents`, and the kind in
   `om/src/<name>/om/agents/README.md`. It writes none of that skill's
   wiring: no `om/src/<name>/om/agents/kinds.py` and no `AGENT_KINDS`,
   no `agent_kinds=` in a container's call to `build_managers`, and
   neither the API's nor the maintenance worker's container test that
   reads that call. Its kinds, every version it still runs, its tools,
   and the classes they declare go in `PRODUCT_KINDS`, in
   `om/src/<name>/om/product_kinds.py` (`agents`, `tools`, `classes`,
   `ceilings` of `ProductKinds` in `om/src/<name>/om/root.py`), which
   every process's entry point hands its root as `PlatformPorts.kinds`.
   A class of the product's that must always wait for a person takes its
   ceiling in `ceilings`, never a row in `DEFAULT_CEILINGS` in the
   platform's `tools/rules.py`, whatever the engine's
   `agentic-scaffold-tool` says for a class. Its container
   test holds instead that the kind declared in `PRODUCT_KINDS.agents`
   reaches each container's `build`, shape
   `workers/session_runner/tests/test_product_parts.py`: the API's
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
   A change to a kind that the last commit holds
   (`git show HEAD:om/src/<name>/om/platform_agents/kinds.py`) is the
   next version, a profile of its own beside the last, and both stay in
   `SHIPPED` while a session may run the last. A kind only this work
   wrote changes in place.
3. A kind names its tools by name and holds no more power than they and
   its policy layer give. A tool the tree has is named by its constant.
   A tool the platform ships for it is a `NativeToolImpl` in `tools.py`,
   shape `ReadSessionImpl` for a read and `HandOffToEngineerImpl` for a
   spawn, registered in `with_shipped`. The engine's
   `agentic-scaffold-tool` holds what a tool's spec, target, and
   failures must be; follow it where it is installed, and the shapes in
   `tools.py` either way, except that a product's class takes its
   ceiling in `PRODUCT_KINDS.ceilings` (step 1). Its test goes in
   `om/tests/unit/test_platform_agents.py`.
   A `result_tool` kind names its result tool among its tools.
4. The profile sets its powers: `isolation` is `WORKSPACE` or
   `NO_WORKSPACE`, and its `policy` is `allowing(...)` the classes it
   needs and no more. A delegated kind with a workspace or a shell is
   refused at boot by `refuse_reach` in `catalog.py` for the assistant;
   a new delegated kind a person talks to is held the same way: add it
   to `refuse_reach`, shape `PLATFORM_ASSISTANT`. Its prompt says what
   it does and what it answers, never how policy treats it.
5. The tests hold, over `SHIPPED`, with the helpers of
   `om/tests/contracts/platform_agents.py` (`platform_over`,
   `Platform.start`, `calls`):
   - the kind is a profile that sets its powers: its tools, its done
     rule, its authority, its isolation, and its classes, in the shape of
     `test_every_shipped_agent_is_a_profile_that_sets_its_powers`, whose
     list of names and set of delivering kinds take the new kind;
   - it ends as its done rule says, over the scripted provider, shape
     `test_analysis_the_planner_and_the_assistant_end_by_their_answer`
     or `test_the_engineers_success_needs_a_passing_validation_at_its_head`;
   - a call past its policy layer is refused, shape
     `test_a_call_from_the_assistant_to_a_workspace_or_a_shell_is_refused`;
   - with `--roles`, a matrix version that serves not every role the
     kind calls is refused, shape
     `test_a_version_that_serves_not_every_role_its_kinds_call_is_refused`
     in `om/tests/unit/test_matrix.py`.

Then the gate, `make check`, as After writing in the conventions
runs it.

## Output

As `../_shared/scaffold-conventions.md` states.
