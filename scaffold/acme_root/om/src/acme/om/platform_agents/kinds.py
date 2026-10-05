"""The agents a platform ships: profiles over the engine's one loop, each
with its own powers. A profile names its tools, its done rule, the
authority its calls run under, its workspace, and its layer of policy; the
engine runs every one of them the same way.

- The engineer takes an objective to a validated, reviewable change in a
  workspace of its own: it edits a file by one place, searches the code,
  opens its pull request on its own branch, so its committed head is on
  the repository, validates that head on a fresh executor, and ends
  through the result gate, citing those runs. It searches and reads the
  knowledge base, and suggests an entry for a person to review.
- Analysis reads what a run produced in a workspace, searches it and the
  knowledge base, changes nothing, and answers with findings.
- The engineer and analysis split independent work, such as hypotheses
  or checks, into sub-agents, each in a clean context of its own, and wait
  for their reports. Every kind takes the engine's tree, three levels deep
  and ten sub-agents besides its root, and each kind a sub-agent may run
  as names its share (ADR 2043).
- The planner turns findings into tasks: it reads where sessions stand,
  hands new engineering work to an engineer, and answers with its plan.
- The platform assistant answers the people who run their part of the
  platform, on their own permissions: it reads the corpus, the knowledge
  base, and the tenant's live records (its sessions and what they wait
  on, its projects, its automations), drafts configuration a person
  applies, and hands engineering work to an engineer. It has no
  workspace, repository, or shell.

A validation session is not here: it runs a check with no agent at all
(`types/validation.py`). Nothing routes a message to one kind or another:
a person chooses by choosing the session they type in."""

from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.om.agent_sessions.limits import Limits
from acme.om.agents.types.kind import NO_WORKSPACE, AgentKind, DoneRule
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.budgets.types.amount import Amount
from acme.om.tools.native.spawn_sub_agent import SPAWN_SUB_AGENT
from acme.om.tools.native.wait_for_sub_agents import WAIT_FOR_SUB_AGENTS
from acme.om.tools.types.policy import Decision, PolicyLayer, PolicyRule
from acme.om.tools.types.tool import ToolClass

ENGINEER = "engineer"
ANALYSIS = "analysis"
PLANNER = "planner"
PLATFORM_ASSISTANT = "platform_assistant"

# The tools the shipped kinds call, by name (`tools.py`).
LIST_FILES = "list_files"
READ_FILE = "read_file"
WRITE_FILE = "write_file"
EDIT_FILE = "edit_file"
SEARCH_CODE = "search_code"
RUN_COMMAND = "run_command"
SUBMIT_RESULT = "submit_result"
VALIDATE = "validate"
OPEN_PULL_REQUEST = "open_pull_request"
SEARCH_CORPUS = "search_corpus"
READ_SESSION = "read_session"
DRAFT_TOOL_POLICY = "draft_tool_policy"
HAND_OFF = "hand_off_to_engineer"
SEARCH_KNOWLEDGE = "search_knowledge"
READ_KNOWLEDGE = "read_knowledge"
SUGGEST_KNOWLEDGE = "suggest_knowledge"
LIST_SESSIONS = "list_sessions"
READ_WAIT = "read_wait"
LIST_PROJECTS = "list_projects"
READ_PROJECT = "read_project"
LIST_AUTOMATIONS = "list_automations"
READ_AUTOMATION = "read_automation"

WORKSPACE = IsolationSpec(mode=IsolationMode.CONTAINER, egress=EgressPolicy(mode=EgressMode.NONE))
"""A container of its own, from which nothing leaves: the workspace of the
kinds that change or read files and run code."""


def allowing(*classes: ToolClass) -> PolicyLayer:
    """A kind's layer of policy: these classes run unattended. A tenant
    narrows or loosens it, and the platform's ceilings hold above both."""
    return PolicyLayer(
        rules=tuple(PolicyRule(authorization_class=c, decision=Decision.ALLOW) for c in classes)
    )


ENGINEER_V1 = AgentKind(
    name=ENGINEER,
    version=1,
    tools=(
        LIST_FILES,
        READ_FILE,
        WRITE_FILE,
        RUN_COMMAND,
        VALIDATE,
        OPEN_PULL_REQUEST,
        SUBMIT_RESULT,
    ),
    done_rule=DoneRule.RESULT_TOOL,
    result_tool=SUBMIT_RESULT,
    authority=AuthorityMode.STEADY,
    prompts=(
        "You are an engineer. You take one objective to a validated, reviewable change "
        "in your workspace. Take a baseline with validate before you change anything. "
        "Change what the objective needs and nothing else, and commit it. Open its pull "
        "request with open_pull_request, so your head is on your branch and a person can "
        "review it, then validate that head. Your branch only moves forward: a fix is a new "
        "commit on top, never an amend or a rebase. Submit the result with submit_result, citing "
        "the runs validate answered: a success counts only when the validation at your "
        "head passed. A failure you explain with those runs is a result too.",
    ),
    # Its pull request is its own work product, so it opens without asking.
    policy=allowing(ToolClass.READ, ToolClass.WRITE, ToolClass.EXECUTE, ToolClass.INTEGRATION),
    isolation=WORKSPACE,
)
"""The engineer before it edited by one place, searched the code, and used
the knowledge base: kept while a session may still run it."""

ENGINEER_V2 = AgentKind(
    name=ENGINEER,
    version=2,
    tools=(
        LIST_FILES,
        READ_FILE,
        SEARCH_CODE,
        EDIT_FILE,
        WRITE_FILE,
        RUN_COMMAND,
        SEARCH_KNOWLEDGE,
        READ_KNOWLEDGE,
        SUGGEST_KNOWLEDGE,
        VALIDATE,
        OPEN_PULL_REQUEST,
        SUBMIT_RESULT,
    ),
    done_rule=DoneRule.RESULT_TOOL,
    result_tool=SUBMIT_RESULT,
    authority=AuthorityMode.STEADY,
    prompts=(
        "You are an engineer. You take one objective to a validated, reviewable change "
        "in your workspace. Take a baseline with validate before you change anything. "
        "Look up what your team already knows with search_knowledge, and find code with "
        "search_code. Change what the objective needs and nothing else: change a file "
        "with edit_file, one place a call, and write a file whole only when it is new. "
        "Commit it. Open its pull request with open_pull_request, so your head is on your "
        "branch and a person can review it, then validate that head. Your branch only "
        "moves forward: a fix is a new commit on top, never an amend or a rebase. Submit "
        "the result with submit_result, citing the runs validate answered: a success "
        "counts only when the validation at your head passed. A failure you explain with "
        "those runs is a result too. When you learned something a later session should "
        "not have to find out again, suggest it with suggest_knowledge.",
    ),
    # Its pull request is its own work product, so it opens without asking.
    policy=allowing(ToolClass.READ, ToolClass.WRITE, ToolClass.EXECUTE, ToolClass.INTEGRATION),
    isolation=WORKSPACE,
)
"""The engineer before it named a share: kept while a session may still run
it."""

ENGINEER_V3 = ENGINEER_V2.model_copy(update={"version": 3, "share": Amount(cost_micros=50_000_000)})
"""The engineer before its step guard was sized for a change: kept while a
session may still run it."""

ENGINEER_STEP_GUARD = 200
"""The model calls one engineer loop makes before it parks for a person. It
is a choice, sized from the task its prompt sets: a baseline validation,
the searches and reads that place the change, edits one place a call, the
commands that run its tests, a commit, its pull request, the validation of
its head, then the fixes that validation asks for and a second one. A
modest change takes about a hundred calls; twice that, so one rarely
parks, and still a guard."""

CACHED_CALL_MICROS = 100_000
"""What one call of the main role over a cached window costs at list price,
as each share counts it: a choice."""

ENGINEER_LOOPS = 3
"""The loops at the step guard one engineer's share pays for: its first,
and two more a follow-up asks for."""

ENGINEER_SHARE = Amount(cost_micros=ENGINEER_LOOPS * ENGINEER_STEP_GUARD * CACHED_CALL_MICROS)
"""What one engineer a spawn starts may spend over its life, in reference
cost: its loops at the step guard over a cached window, which is also many
of the main role's worst-case calls at a full window, so its first call is
never refused. Its tree's budget still bounds it, and a share never raises
that budget."""

ENGINEER_V4 = ENGINEER_V3.model_copy(
    update={
        "version": 4,
        "share": ENGINEER_SHARE,
        "limits": Limits(step_guard=ENGINEER_STEP_GUARD),
    }
)
"""The engineer before it started sub-agents: kept while a session may
still run it."""

SUB_AGENTS = (
    "When the work splits into questions that do not depend on each other, such as "
    "hypotheses to test or checks to run, start a sub-agent for each with "
    "spawn_sub_agent: a short title, and an objective that stands on its own, since a "
    "sub-agent sees none of your history. Keep working, or wait for their reports with "
    "wait_for_sub_agents; each report wakes you. Start one only for work worth a session "
    "of its own: every sub-agent spends from the budget your whole tree shares. A "
    "sub-agent works on a fresh checkout of the default branch, without your changes: ask "
    "it about what is on the default branch, or hand it what it needs in its objective."
)
"""The prompt layer of a kind that starts sub-agents."""

ENGINEER_SPLITS = (
    f'Start a sub-agent of kind "{ANALYSIS}" for a question that only reads or checks, '
    "such as a hypothesis to test or a check to run: it changes nothing and spends less. "
    f'Start one of your own kind, "{ENGINEER}" (or leave kind out), only for work that '
    "changes code: it opens a pull request of its own."
)
"""The engineer's layer on which kind a sub-agent runs as, so a question it
splits off runs as analysis, under analysis's share, and not as another
engineer."""

ENGINEER_KIND = ENGINEER_V4.model_copy(
    update={
        "version": 5,
        "tools": (
            LIST_FILES,
            READ_FILE,
            SEARCH_CODE,
            EDIT_FILE,
            WRITE_FILE,
            RUN_COMMAND,
            SEARCH_KNOWLEDGE,
            READ_KNOWLEDGE,
            SUGGEST_KNOWLEDGE,
            SPAWN_SUB_AGENT,
            WAIT_FOR_SUB_AGENTS,
            VALIDATE,
            OPEN_PULL_REQUEST,
            SUBMIT_RESULT,
        ),
        "prompts": (*ENGINEER_V4.prompts, SUB_AGENTS, ENGINEER_SPLITS),
        # A sub-agent's calls are still decided under its own kind's
        # policy and under this one, and the strictest holds.
        "policy": allowing(
            ToolClass.READ,
            ToolClass.WRITE,
            ToolClass.EXECUTE,
            ToolClass.INTEGRATION,
            ToolClass.SPAWN,
        ),
    }
)
"""The engineer. It starts sub-agents and waits on them, and since it
delivers through its result tool, a product's kind may spawn it too, under
its share."""

ANALYSIS_V1 = AgentKind(
    name=ANALYSIS,
    version=1,
    tools=(LIST_FILES, READ_FILE, RUN_COMMAND),
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.STEADY,
    prompts=(
        "You read what a run produced (its logs, its telemetry, its recordings) in your "
        "workspace, and turn it into findings. Change nothing. Answer with the findings, "
        "each citing the files and the commands that show it.",
    ),
    policy=allowing(ToolClass.READ, ToolClass.EXECUTE),
    isolation=WORKSPACE,
)
"""Analysis before it searched its workspace and the knowledge base: kept
while a session may still run it."""

ANALYSIS_V2 = AgentKind(
    name=ANALYSIS,
    version=2,
    tools=(LIST_FILES, READ_FILE, SEARCH_CODE, RUN_COMMAND, SEARCH_KNOWLEDGE, READ_KNOWLEDGE),
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.STEADY,
    prompts=(
        "You read what a run produced (its logs, its telemetry, its recordings) in your "
        "workspace, and turn it into findings. Search it with search_code, and look up "
        "what your team already knows with search_knowledge. Change nothing. Answer with "
        "the findings, each citing the files and the commands that show it.",
    ),
    policy=allowing(ToolClass.READ, ToolClass.EXECUTE),
    isolation=WORKSPACE,
)
"""Analysis before it started sub-agents and named a share: kept while a
session may still run it."""

ANALYSIS_LOOPS = 2
"""The loops at its step guard, the engine's, one analysis's share pays
for: its first, and one more a follow-up asks for."""

ANALYSIS_SHARE = Amount(cost_micros=ANALYSIS_LOOPS * Limits().step_guard * CACHED_CALL_MICROS)
"""What one analysis a spawn starts may spend over its life, in reference
cost: its loops at the engine's step guard over a cached window, which is
also more than three of the main role's worst-case calls at a full
window, so its first call is never refused. Its tree's budget still
bounds it, and a share never raises that budget."""

ANALYSIS_WAITS = (
    "Once you start a sub-agent, wait for every sub-agent's report with "
    "wait_for_sub_agents before you answer: a turn with no tool call is your answer, and "
    "it ends your session."
)
"""Analysis's layer on its sub-agents: it answers with a turn that calls no
tool, so it waits for every report before that turn."""

ANALYSIS_KIND = ANALYSIS_V2.model_copy(
    update={
        "version": 3,
        "tools": (*ANALYSIS_V2.tools, SPAWN_SUB_AGENT, WAIT_FOR_SUB_AGENTS),
        "prompts": (*ANALYSIS_V2.prompts, SUB_AGENTS, ANALYSIS_WAITS),
        "policy": allowing(ToolClass.READ, ToolClass.EXECUTE, ToolClass.SPAWN),
        "share": ANALYSIS_SHARE,
    }
)
"""Analysis. It starts sub-agents of its own, and a spawn may start it, the
way an engineer splits a question, so it names a share."""

PLANNER_KIND = AgentKind(
    name=PLANNER,
    version=1,
    tools=(READ_SESSION, HAND_OFF),
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.STEADY,
    prompts=(
        "You turn findings into tasks. For each task, decide whether an existing session "
        "should continue it or a new one should start: read where a session stands with "
        "read_session, and hand new engineering work to an engineer with "
        "hand_off_to_engineer, with an objective that stands on its own. Answer with the "
        "plan: each task and the session it goes to.",
    ),
    policy=allowing(ToolClass.READ, ToolClass.SPAWN),
)

PLATFORM_ASSISTANT_V1 = AgentKind(
    name=PLATFORM_ASSISTANT,
    version=1,
    tools=(SEARCH_CORPUS, READ_SESSION, DRAFT_TOOL_POLICY, HAND_OFF),
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    prompts=(
        "You help the people who set up and run their part of the platform. Explain the "
        "product only from what search_corpus finds, and cite the document of every "
        "passage you use. Diagnose live state with read_session, never by guessing. Draft "
        "a change to the tool policy with draft_tool_policy and show the difference from "
        "what is live: a person applies it, never you. When the work is engineering, hand "
        "it to an engineer with hand_off_to_engineer and an objective that stands on its "
        "own, then step back.",
    ),
    policy=allowing(ToolClass.READ, ToolClass.SPAWN),
    isolation=NO_WORKSPACE,
)
"""The platform assistant before it read the tenant's sessions, projects,
and automations, and its knowledge: kept while a session may still run
it."""

ASSISTANT_READERS = (
    READ_SESSION,
    LIST_SESSIONS,
    READ_WAIT,
    LIST_PROJECTS,
    READ_PROJECT,
    LIST_AUTOMATIONS,
    READ_AUTOMATION,
)
"""The assistant's readers of the tenant's live records, each through the
asking person's own permissions."""

PLATFORM_ASSISTANT_KIND = AgentKind(
    name=PLATFORM_ASSISTANT,
    version=2,
    tools=(
        SEARCH_CORPUS,
        SEARCH_KNOWLEDGE,
        READ_KNOWLEDGE,
        *ASSISTANT_READERS,
        DRAFT_TOOL_POLICY,
        HAND_OFF,
    ),
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    prompts=(
        "You help the people who set up and run their part of the platform. Explain the "
        "product only from what search_corpus and search_knowledge find, and cite the "
        "document of every passage you use: docs/object-model.md says what each thing is, "
        "what owns it, and what moves it between its states. docs/portal-routes.md lists "
        "the portal's pages: when you name a page, link it by its address as that "
        "document says, so the person can open it. Diagnose by reading first, "
        "never by guessing. Find sessions with list_sessions and read one with "
        "read_session; read what a waiting session waits on, its place in the work queue "
        "and the hosts that run it, with read_wait; read projects and automations, and an "
        "automation's recent runs, the same way, and any other reader you hold. When "
        "something waits or is slow, say what it waits on as you read it, what clears it, "
        "who may clear it, and where they do. Draft a change to the tool policy with "
        "draft_tool_policy and show the difference from what is live: a person applies "
        "it, never you. When the work is engineering, hand it to an engineer with "
        "hand_off_to_engineer and an objective that stands on its own, then step back.",
    ),
    policy=allowing(ToolClass.READ, ToolClass.SPAWN),
    isolation=NO_WORKSPACE,
)
"""The platform assistant. A product adds its own readers to it through its
slot (`ProductKinds.assistant_tools`), which the root joins to this version
alone."""

SHIPPED: tuple[AgentKind, ...] = (
    ENGINEER_V1,
    ENGINEER_V2,
    ENGINEER_V3,
    ENGINEER_V4,
    ENGINEER_KIND,
    ANALYSIS_V1,
    ANALYSIS_V2,
    ANALYSIS_KIND,
    PLANNER_KIND,
    PLATFORM_ASSISTANT_V1,
    PLATFORM_ASSISTANT_KIND,
)
"""Every kind the platform ships, at every version it still runs."""
