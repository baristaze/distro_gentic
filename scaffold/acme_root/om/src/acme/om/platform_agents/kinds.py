"""The agents a platform ships: profiles over the engine's one loop, each
with its own powers. A profile names its tools, its done rule, the
authority its calls run under, its workspace, and its layer of policy; the
engine runs every one of them the same way.

- The software engineer takes an objective to a validated, reviewable change in a
  workspace of its own: it edits a file by one place, searches the code,
  opens its pull request on its own branch, so its committed head is on
  the repository, validates that head on a fresh executor, and ends
  through the result gate, citing those runs. It searches and reads the
  agent knowledge base, and suggests an entry for a person to review.
- Analysis reads what a run produced in a workspace, searches it and the
  agent knowledge base, changes nothing, and answers with findings.
- The software engineer and analysis split independent work, such as hypotheses
  or checks, into sub-agents, each in a clean context of its own, and wait
  for their reports. Every kind takes the engine's tree, three levels deep
  and ten sub-agents besides its root, and each kind a sub-agent may run
  as names its share (ADR 2043).
- The planner turns findings into tasks: it reads where sessions stand,
  hands new engineering work to a software engineer, and answers with its plan.
- The platform assistant answers the people who run their part of the
  platform, on their own permissions: it reads the corpus, the agent knowledge
  base, and the tenant's live records (its sessions and what they wait
  on, its agent projects, its agent automations), drafts configuration a person
  applies, and hands engineering work to a software engineer. It has no
  workspace, repository, or shell.
- The reviewer reads one pull request through the forge: its files and
  their patches, its checks, and a file at its head. It notes each
  finding with its file, its line, and its grade, and submits its review
  through its result tool, citing them. It has no workspace and changes
  nothing; it comments on the pull request only through the forge's
  integration, and a person approves each comment. It asks XL of its main
  role.
- The ops analyst reads the tenant's operations on its person's own
  permissions: its sessions and what they wait on, its hosts and what they
  offer, its budgets and their spend. Every tool it holds reads; a fix it
  finds leaves as an objective a person hands to a software engineer.

A lead is a kind like any other, whose toolsets include `sub_agents`: it
starts the others as sub-agents, such as a software engineer on a change and a
reviewer on the pull request the software engineer opens, and answers with their
reports.

Every kind is built from the platform's toolsets (`TOOLSETS`), with a few
tools named alone where a toolset would give it more than it may call. It
asks a model size of each model role it calls (`ASKS`), and carries its
warm grace (`GRACES`): how long its workspace stays held after a loop for
a follow-up.

A validation session is not here: it runs a check with no agent at all
(`types/validation.py`). Nothing routes a message to one kind or another:
a person chooses by choosing the session they type in."""

from collections.abc import Mapping
from datetime import timedelta
from enum import StrEnum
from typing import Any

from acme.infra.agent_workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.om.agent_sessions.limits import Limits
from acme.om.agents.types.kind import NO_AGENT_WORKSPACE, AgentKind, DoneRule
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import OmBase
from acme.om.context import Permission
from acme.om.language_models.types.fill import MAIN, SUMMARIZER, ModelAsk, ModelSize
from acme.om.spend_budgets.types.amount import Amount
from acme.om.tools.native.spawn_sub_agent import SPAWN_SUB_AGENT
from acme.om.tools.native.wait_for_sub_agents import WAIT_FOR_SUB_AGENTS
from acme.om.tools.types.policy import Decision, ToolPolicyLayer, ToolPolicyRule
from acme.om.tools.types.tool import ToolClass
from acme.om.tools.types.toolset import Toolset
from acme.om.windows.rules import READ_TOOL_OUTPUT
from acme.om.work.kinds import WorkKindSpec

SOFTWARE_ENGINEER = "software_engineer"
ANALYSIS = "analysis"
PLANNER = "planner"
PLATFORM_ASSISTANT = "platform_assistant"
REVIEWER = "reviewer"
OPS_ANALYST = "ops_analyst"

# The tools the shipped kinds call, by name (`tools/`).
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
READ_AGENT_SESSION = "read_agent_session"
DRAFT_TOOL_POLICY = "draft_tool_policy"
HAND_OFF = "hand_off_to_software_engineer"
SEARCH_AGENT_KNOWLEDGE = "search_agent_knowledge"
READ_AGENT_KNOWLEDGE = "read_agent_knowledge"
SUGGEST_AGENT_KNOWLEDGE = "suggest_agent_knowledge"
LIST_AGENT_SESSIONS = "list_agent_sessions"
READ_WAIT = "read_wait"
LIST_AGENT_PROJECTS = "list_agent_projects"
READ_AGENT_PROJECT = "read_agent_project"
LIST_AGENT_AUTOMATIONS = "list_agent_automations"
READ_AGENT_AUTOMATION = "read_agent_automation"
READ_PULL_REQUEST = "read_pull_request"
READ_PULL_REQUEST_FILE = "read_pull_request_file"
NOTE_FINDING = "note_finding"
SUBMIT_REVIEW = "submit_review"
COMMENT = "comment"  # the forge's, `intake.tools`
LIST_HOSTS = "list_hosts"
READ_SPEND = "read_spend"

ASSISTANT_READERS = (
    READ_AGENT_SESSION,
    LIST_AGENT_SESSIONS,
    READ_WAIT,
    LIST_AGENT_PROJECTS,
    READ_AGENT_PROJECT,
    LIST_AGENT_AUTOMATIONS,
    READ_AGENT_AUTOMATION,
)
"""The assistant's readers of the tenant's live records, each through the
asking person's own context."""

# The platform's toolsets: each a group of tools a kind takes whole. A tool
# a toolset holds that a kind may not call keeps the kind off that toolset,
# and the kind names the tools it may call alone.

FILES_TOOLSET = Toolset(
    name="files",
    version=1,
    summary="List, read, and search the files in your workspace.",
    tools=(LIST_FILES, READ_FILE, SEARCH_CODE),
)
CODE_TOOLSET = Toolset(
    name="code",
    version=1,
    summary="Change the files in your workspace, one place at a time or whole, and run commands.",
    tools=(EDIT_FILE, WRITE_FILE, RUN_COMMAND),
)
AGENT_KNOWLEDGE_TOOLSET = Toolset(
    name="agent_knowledge",
    version=1,
    summary="Search and read what your team already knows.",
    tools=(SEARCH_AGENT_KNOWLEDGE, READ_AGENT_KNOWLEDGE),
)
WORK_PRODUCT_TOOLSET = Toolset(
    name="work_product",
    version=1,
    summary="Validate your change, open its pull request, and submit your result.",
    tools=(VALIDATE, OPEN_PULL_REQUEST, SUBMIT_RESULT),
)
SUB_AGENTS_TOOLSET = Toolset(
    name="sub_agents",
    version=1,
    summary="Start a sub-agent on a question of its own, and wait for the reports.",
    tools=(SPAWN_SUB_AGENT, WAIT_FOR_SUB_AGENTS),
)
RECORDS_TOOLSET = Toolset(
    name="records",
    version=1,
    summary="Read the tenant's sessions and what they wait on, its agent projects, and its agent automations.",
    tools=ASSISTANT_READERS,
)
HANDOFF_TOOLSET = Toolset(
    name="handoff",
    version=1,
    summary="Hand engineering work to a software engineer, in a session of its own.",
    tools=(HAND_OFF,),
)
TOOL_OUTPUTS_TOOLSET = Toolset(
    name="tool_outputs",
    version=1,
    summary="Read back a result kept outside your window, by the handle its notice names.",
    tools=(READ_TOOL_OUTPUT,),
)

REVIEW_TOOLSET = Toolset(
    name="review",
    version=1,
    summary=(
        "Read a pull request, its checks, and its files at its head; note each finding, and "
        "submit your review."
    ),
    tools=(READ_PULL_REQUEST, READ_PULL_REQUEST_FILE, NOTE_FINDING, SUBMIT_REVIEW),
)
OPERATIONS_TOOLSET = Toolset(
    name="operations",
    version=1,
    summary="Read the tenant's hosts and what each offers, and what its budgets spent.",
    tools=(LIST_HOSTS, READ_SPEND),
)

TOOLSETS: tuple[Toolset, ...] = (
    FILES_TOOLSET,
    CODE_TOOLSET,
    AGENT_KNOWLEDGE_TOOLSET,
    WORK_PRODUCT_TOOLSET,
    SUB_AGENTS_TOOLSET,
    RECORDS_TOOLSET,
    HANDOFF_TOOLSET,
    TOOL_OUTPUTS_TOOLSET,
    REVIEW_TOOLSET,
    OPERATIONS_TOOLSET,
)
"""The platform's catalog of toolsets, which a product's kinds name as the
platform's do. A product adds toolsets of its own beside them
(`ProductKinds.toolsets`) and never changes one of these."""

ASKS = (ModelAsk(role=MAIN, size=ModelSize.L), ModelAsk(role=SUMMARIZER, size=ModelSize.S))
"""What every shipped kind but the reviewer asks of its two model roles: L
of its own turns and S of its compaction, each at its fill's own effort.
They are the sizes of the models those roles ran on before any kind
asked."""

REVIEWER_ASKS = (
    ModelAsk(role=MAIN, size=ModelSize.XL),
    ModelAsk(role=SUMMARIZER, size=ModelSize.S),
)
"""What the reviewer asks: XL of its own turns, since a review is worth the
defects it finds and a larger model finds more, and S of its compaction."""

PROMPT_CACHE_LIFE = timedelta(minutes=5)
"""How long a provider the platform calls keeps a request's cached prefix
after its last use, at the shortest of them. A follow-up later than this
writes its prefix again, so holding a workspace for it saves little: no
kind's warm grace runs past it."""

WARM_GRACE = PROMPT_CACHE_LIFE
"""The warm grace of a kind that names none."""

GRACES: Mapping[str, timedelta] = {
    SOFTWARE_ENGINEER: PROMPT_CACHE_LIFE,
    ANALYSIS: PROMPT_CACHE_LIFE,
}
"""Each shipped kind's warm grace, by name, every version of it: how long
its workspace stays held after a loop, for a follow-up to find it warm. The
planner and the assistant have no workspace to hold."""


def revised(kind: AgentKind, **update: Any) -> AgentKind:
    """`kind` with `update`, built again, so a toolset it adds folds into
    its tools as it does in a kind declared whole."""
    return AgentKind.model_validate({**dict(kind), **update})


WORKSPACE = IsolationSpec(mode=IsolationMode.CONTAINER, egress=EgressPolicy(mode=EgressMode.NONE))
"""A container of its own, from which nothing leaves: the workspace of the
kinds that change or read files and run code."""


def allowing(*classes: ToolClass) -> ToolPolicyLayer:
    """A kind's layer of policy: these classes run unattended. A tenant
    narrows or loosens it, and the platform's ceilings hold above both."""
    return ToolPolicyLayer(
        rules=tuple(ToolPolicyRule(authorization_class=c, decision=Decision.ALLOW) for c in classes)
    )


SOFTWARE_ENGINEER_V1 = AgentKind(
    name=SOFTWARE_ENGINEER,
    version=1,
    tools=(LIST_FILES, READ_FILE, WRITE_FILE, RUN_COMMAND),
    toolsets=(WORK_PRODUCT_TOOLSET,),
    asks=ASKS,
    done_rule=DoneRule.RESULT_TOOL,
    result_tool=SUBMIT_RESULT,
    authority=AuthorityMode.STEADY,
    prompts=(
        "You are a software engineer. You take one objective to a validated, reviewable change "
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
"""The software engineer before it edited by one place, searched the code, and used
the agent knowledge base: kept while a session may still run it."""

SOFTWARE_ENGINEER_V2 = AgentKind(
    name=SOFTWARE_ENGINEER,
    version=2,
    tools=(SUGGEST_AGENT_KNOWLEDGE,),
    toolsets=(FILES_TOOLSET, CODE_TOOLSET, AGENT_KNOWLEDGE_TOOLSET, WORK_PRODUCT_TOOLSET),
    asks=ASKS,
    done_rule=DoneRule.RESULT_TOOL,
    result_tool=SUBMIT_RESULT,
    authority=AuthorityMode.STEADY,
    prompts=(
        "You are a software engineer. You take one objective to a validated, reviewable change "
        "in your workspace. Take a baseline with validate before you change anything. "
        "Look up what your team already knows with search_agent_knowledge, and find code with "
        "search_code. Change what the objective needs and nothing else: change a file "
        "with edit_file, one place a call, and write a file whole only when it is new. "
        "Commit it. Open its pull request with open_pull_request, so your head is on your "
        "branch and a person can review it, then validate that head. Your branch only "
        "moves forward: a fix is a new commit on top, never an amend or a rebase. Submit "
        "the result with submit_result, citing the runs validate answered: a success "
        "counts only when the validation at your head passed. A failure you explain with "
        "those runs is a result too. When you learned something a later session should "
        "not have to find out again, suggest it with suggest_agent_knowledge.",
    ),
    # Its pull request is its own work product, so it opens without asking.
    policy=allowing(ToolClass.READ, ToolClass.WRITE, ToolClass.EXECUTE, ToolClass.INTEGRATION),
    isolation=WORKSPACE,
)
"""The software engineer before it named a share: kept while a session may still run
it."""

SOFTWARE_ENGINEER_V3 = SOFTWARE_ENGINEER_V2.model_copy(
    update={"version": 3, "share": Amount(cost_micros=50_000_000)}
)
"""The software engineer before its step guard was sized for a change: kept while a
session may still run it."""

SOFTWARE_ENGINEER_STEP_GUARD = 200
"""The model calls one software engineer loop makes before it parks for a person. It
is a choice, sized from the task its prompt sets: a baseline validation,
the searches and reads that place the change, edits one place a call, the
commands that run its tests, a commit, its pull request, the validation of
its head, then the fixes that validation asks for and a second one. A
modest change takes about a hundred calls; twice that, so one rarely
parks, and still a guard."""

CACHED_CALL_MICROS = 100_000
"""What one call of the main role over a cached window costs at list price,
as each share counts it: a choice."""

SOFTWARE_ENGINEER_LOOPS = 3
"""The loops at the step guard one software engineer's share pays for: its first,
and two more a follow-up asks for."""

SOFTWARE_ENGINEER_SHARE = Amount(
    cost_micros=SOFTWARE_ENGINEER_LOOPS * SOFTWARE_ENGINEER_STEP_GUARD * CACHED_CALL_MICROS
)
"""What one software engineer a spawn starts may spend over its life, in reference
cost: its loops at the step guard over a cached window, which is also many
of the main role's worst-case calls at a full window, so its first call is
never refused. Its tree's budget still bounds it, and a share never raises
that budget."""

SOFTWARE_ENGINEER_V4 = SOFTWARE_ENGINEER_V3.model_copy(
    update={
        "version": 4,
        "share": SOFTWARE_ENGINEER_SHARE,
        "limits": Limits(step_guard=SOFTWARE_ENGINEER_STEP_GUARD),
    }
)
"""The software engineer before it started sub-agents: kept while a session may
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

SOFTWARE_ENGINEER_SPLITS = (
    f'Start a sub-agent of kind "{ANALYSIS}" for a question that only reads or checks, '
    "such as a hypothesis to test or a check to run: it changes nothing and spends less. "
    f'Start one of your own kind, "{SOFTWARE_ENGINEER}" (or leave kind out), only for work that '
    "changes code: it opens a pull request of its own."
)
"""The software engineer's layer on which kind a sub-agent runs as, so a question it
splits off runs as analysis, under analysis's share, and not as another
software engineer."""

SOFTWARE_ENGINEER_V5 = revised(
    SOFTWARE_ENGINEER_V4,
    version=5,
    toolsets=(*SOFTWARE_ENGINEER_V4.toolsets, SUB_AGENTS_TOOLSET),
    prompts=(*SOFTWARE_ENGINEER_V4.prompts, SUB_AGENTS, SOFTWARE_ENGINEER_SPLITS),
    # A sub-agent's calls are still decided under its own kind's policy and
    # under this one, and the strictest holds.
    policy=allowing(
        ToolClass.READ,
        ToolClass.WRITE,
        ToolClass.EXECUTE,
        ToolClass.INTEGRATION,
        ToolClass.SPAWN,
    ),
)
"""The software engineer before it took a baseline again when its base moved: kept
while a session may still run it."""

BASE_MOVES = (
    "Take a baseline again whenever your base moves, as when your branch takes the default "
    "branch in or is cut again, then validate your head again: a success counts only when a "
    "baseline at its base ran before its head was validated."
)
"""The software engineer's layer on a base that moves, so feedback after its pull
request merged, on a branch cut again, can still end in a success."""

SOFTWARE_ENGINEER_V6 = SOFTWARE_ENGINEER_V5.model_copy(
    update={"version": 6, "prompts": (*SOFTWARE_ENGINEER_V5.prompts, BASE_MOVES)}
)
"""The software engineer before it read back a result kept outside its window:
kept while a session may still run it."""

SOFTWARE_ENGINEER_V7 = revised(
    SOFTWARE_ENGINEER_V6, version=7, toolsets=(*SOFTWARE_ENGINEER_V6.toolsets, TOOL_OUTPUTS_TOOLSET)
)
"""The software engineer before its workspace started from its agent project's
workspace base: kept while a session may still run it."""

AGENT_WORKSPACE_BASE = (
    "Your workspace has no network. What your work needs installed comes from your agent project's "
    "environment, set up before you start. When the work needs a package your workspace "
    "lacks, do not try to install it: say which one in your result."
)
"""The software engineer's layer on its agent project's workspace base, so a missing package
is named rather than fetched through a network it does not have."""

SOFTWARE_ENGINEER_KIND = SOFTWARE_ENGINEER_V7.model_copy(
    update={"version": 8, "prompts": (*SOFTWARE_ENGINEER_V7.prompts, AGENT_WORKSPACE_BASE)}
)
"""The software engineer. It starts sub-agents and waits on them, and since it
delivers through its result tool, a product's kind may spawn it too, under
its share. A result too large for its window, or one compaction elided, it
reads back with `read_tool_output`, by the handle the notice names. Its
workspace starts from its agent project's workspace base, when the agent project names
one, and keeps no egress (`WORKSPACE_BASE_KINDS`)."""

WORKSPACE_BASE_KINDS: frozenset[tuple[str, int]] = frozenset({(SOFTWARE_ENGINEER, 8)})
"""The platform's kinds, by name and version, whose workspace starts from
the workspace base its session's agent project names: the software engineer from version 8.
A later version that takes it joins here; the versions before it keep
their own base. A product names its own beside these, in its slot
(`platform_root.ProductKinds.workspace_bases`)."""

ANALYSIS_V1 = AgentKind(
    name=ANALYSIS,
    version=1,
    tools=(LIST_FILES, READ_FILE, RUN_COMMAND),
    asks=ASKS,
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
"""Analysis before it searched its workspace and the agent knowledge base: kept
while a session may still run it."""

ANALYSIS_V2 = AgentKind(
    name=ANALYSIS,
    version=2,
    # It runs commands and changes no file, so it names its shell alone.
    tools=(RUN_COMMAND,),
    toolsets=(FILES_TOOLSET, AGENT_KNOWLEDGE_TOOLSET),
    asks=ASKS,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.STEADY,
    prompts=(
        "You read what a run produced (its logs, its telemetry, its recordings) in your "
        "workspace, and turn it into findings. Search it with search_code, and look up "
        "what your team already knows with search_agent_knowledge. Change nothing. Answer with "
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

ANALYSIS_V3 = revised(
    ANALYSIS_V2,
    version=3,
    toolsets=(*ANALYSIS_V2.toolsets, SUB_AGENTS_TOOLSET),
    prompts=(*ANALYSIS_V2.prompts, SUB_AGENTS, ANALYSIS_WAITS),
    policy=allowing(ToolClass.READ, ToolClass.EXECUTE, ToolClass.SPAWN),
    share=ANALYSIS_SHARE,
)
"""Analysis before it read back a result kept outside its window: kept
while a session may still run it."""

ANALYSIS_KIND = revised(
    ANALYSIS_V3, version=4, toolsets=(*ANALYSIS_V3.toolsets, TOOL_OUTPUTS_TOOLSET)
)
"""Analysis. It starts sub-agents of its own, and a spawn may start it, the
way a software engineer splits a question, so it names a share. A result too large
for its window, or one compaction elided, it reads back with
`read_tool_output`, by the handle the notice names."""

PLANNER_KIND = AgentKind(
    name=PLANNER,
    version=1,
    # It reads one session, never the tenant's other records.
    tools=(READ_AGENT_SESSION,),
    toolsets=(HANDOFF_TOOLSET,),
    asks=ASKS,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.STEADY,
    prompts=(
        "You turn findings into tasks. For each task, decide whether an existing session "
        "should continue it or a new one should start: read where a session stands with "
        "read_agent_session, and hand new engineering work to a software engineer with "
        "hand_off_to_software_engineer, with an objective that stands on its own. Answer with the "
        "plan: each task and the session it goes to.",
    ),
    policy=allowing(ToolClass.READ, ToolClass.SPAWN),
)

PLATFORM_ASSISTANT_V1 = AgentKind(
    name=PLATFORM_ASSISTANT,
    version=1,
    tools=(SEARCH_CORPUS, READ_AGENT_SESSION, DRAFT_TOOL_POLICY),
    toolsets=(HANDOFF_TOOLSET,),
    asks=ASKS,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    prompts=(
        "You help the people who set up and run their part of the platform. Explain the "
        "product only from what search_corpus finds, and cite the document of every "
        "passage you use. Diagnose live state with read_agent_session, never by guessing. Draft "
        "a change to the tool policy with draft_tool_policy and show the difference from "
        "what is live: a person applies it, never you. When the work is engineering, hand "
        "it to a software engineer with hand_off_to_software_engineer and an objective that stands on its "
        "own, then step back.",
    ),
    policy=allowing(ToolClass.READ, ToolClass.SPAWN),
    isolation=NO_AGENT_WORKSPACE,
)
"""The platform assistant before it read the tenant's sessions, agent projects,
and agent automations, and its agent knowledge: kept while a session may still run
it."""

PLATFORM_ASSISTANT_KIND = AgentKind(
    name=PLATFORM_ASSISTANT,
    version=2,
    tools=(SEARCH_CORPUS, DRAFT_TOOL_POLICY),
    toolsets=(AGENT_KNOWLEDGE_TOOLSET, RECORDS_TOOLSET, HANDOFF_TOOLSET),
    asks=ASKS,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    prompts=(
        "You help the people who set up and run their part of the platform. Explain the "
        "product only from what search_corpus and search_agent_knowledge find, and cite the "
        "document of every passage you use: docs/object-model.md says what each thing is, "
        "what owns it, and what moves it between its states. docs/portal-routes.md lists "
        "the portal's pages: when you name a page, link it by its address as that "
        "document says, so the person can open it. Diagnose by reading first, "
        "never by guessing. Find sessions with list_agent_sessions and read one with "
        "read_agent_session; read what a waiting session waits on, its place in the work queue "
        "and the hosts that run it, with read_wait; read agent projects and agent_automations, and an "
        "agent_automation's recent runs, the same way, and any other reader you hold. When "
        "something waits or is slow, say what it waits on as you read it, what clears it, "
        "who may clear it, and where they do. Draft a change to the tool policy with "
        "draft_tool_policy and show the difference from what is live: a person applies "
        "it, never you. When the work is engineering, hand it to a software engineer with "
        "hand_off_to_software_engineer and an objective that stands on its own, then step back.",
    ),
    policy=allowing(ToolClass.READ, ToolClass.SPAWN),
    isolation=NO_AGENT_WORKSPACE,
)
"""The platform assistant. A product adds its own readers to it through its
slot (`ProductKinds.assistant_tools`), which the root joins to this version
alone."""

REVIEWER_PROMPT = (
    "You review one pull request, named in what you were asked as owner/repo#12. Read it with "
    "read_pull_request: its head, the files it changes with their patches, and its checks. "
    "When a patch shows too little, read the whole file at the head with "
    "read_pull_request_file, and look up what your team already knows with search_agent_knowledge. "
    "Note each defect you find with note_finding: the file, its line at the head, a grade, "
    "and what is wrong and what it does in real use. Grade it high for harm that cannot be "
    "undone or a wrong result on the path the change exists for, medium for a wrong result "
    "on another path real use takes, and low for anything else. A matter of taste is no "
    "finding. You change nothing: no tool you hold writes a file, runs code, or pushes. When "
    "every finding is noted, or you found none, list them, one line each with its file and "
    "line first, since that list is what whoever asked reads. In the same turn, submit the "
    "review with submit_review, citing the ids read_pull_request and note_finding answered. "
    "A read of a pull request too large for one answer counts the files it left out: say "
    "how many in your list. A review you could not finish is a result too: submit it as "
    "failed, citing the reads that show why; a read that fails names its id in its failure. "
    "Comment on the pull request with comment only when you are asked to: a person approves "
    "each comment before it is posted."
)
"""The reviewer's layer: what it reads, how it grades, and how it delivers."""

XL_CALL_FACTOR = 2
"""What one call of a main role at XL costs against one at L, at the list
prices of the models the two sizes run on: twice. A choice."""

REVIEWER_LOOPS = 2
"""The loops at its step guard, the engine's, one reviewer's share pays
for: its review, and one more a follow-up asks for."""

REVIEWER_SHARE = Amount(
    cost_micros=REVIEWER_LOOPS * Limits().step_guard * CACHED_CALL_MICROS * XL_CALL_FACTOR
)
"""What one reviewer a spawn starts may spend over its life, in reference
cost: its loops at the engine's step guard over a cached window at XL,
which is also more than three of XL's worst-case calls at a full window,
so its first call is never refused. Its tree's budget still bounds it, and
a share never raises that budget."""

REVIEWER_KIND = AgentKind(
    name=REVIEWER,
    version=1,
    # It comments on what it reviews through the forge's integration, and a
    # person approves each comment: the platform's ceiling holds every
    # outward call, and its own layer runs no integration unattended.
    tools=(COMMENT,),
    toolsets=(REVIEW_TOOLSET, AGENT_KNOWLEDGE_TOOLSET, TOOL_OUTPUTS_TOOLSET),
    asks=REVIEWER_ASKS,
    done_rule=DoneRule.RESULT_TOOL,
    result_tool=SUBMIT_REVIEW,
    authority=AuthorityMode.STEADY,
    prompts=(REVIEWER_PROMPT,),
    policy=allowing(ToolClass.READ),
    isolation=NO_AGENT_WORKSPACE,
    share=REVIEWER_SHARE,
)
"""The reviewer. It reads one pull request through the forge, at its head,
and changes nothing: it has no workspace, and no tool it holds writes a
file, runs code, or pushes. It delivers its review through its result
tool, citing the findings it noted, and its share lets a lead start it as
a sub-agent on the pull request another kind opened."""

OPS_ANALYST_PROMPT = (
    "You read how the tenant's part of the platform runs, and you change nothing: every "
    "tool you hold reads. Find sessions with list_agent_sessions and read one with read_agent_session. "
    "Read what a waiting session waits on with read_wait: its loop's place on the work "
    "queue, its lane, the loops running ahead of it, and the hosts that may run it. Read the "
    "tenant's hosts and what each offers with list_hosts, its budgets and what they spent "
    "with read_spend, and its agent projects and agent automations with their readers. Explain only from "
    "what search_agent_knowledge finds, and cite the document of every passage you use. Diagnose "
    "by reading first, never by guessing: say what something waits on as you read it, what "
    "clears it, who may clear it, and where they do. When the fix is engineering, write it "
    "as an objective that stands on its own, for a person to hand to a software engineer: you start "
    "no session and apply nothing."
)
"""The ops analyst's layer: what it reads, and how a fix leaves it."""

OPS_ANALYST_KIND = AgentKind(
    name=OPS_ANALYST,
    version=1,
    toolsets=(RECORDS_TOOLSET, OPERATIONS_TOOLSET, AGENT_KNOWLEDGE_TOOLSET, TOOL_OUTPUTS_TOOLSET),
    asks=ASKS,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    prompts=(OPS_ANALYST_PROMPT,),
    policy=allowing(ToolClass.READ),
    isolation=NO_AGENT_WORKSPACE,
)
"""The ops analyst. It reads the tenant's operations on its person's own
permissions: its sessions and what they wait on, its hosts and what they
offer, its budgets and their spend, its agent projects and agent automations. Every
tool it holds reads, so it changes nothing; a fix it finds leaves as an
objective a person hands to a software engineer."""

SHIPPED: tuple[AgentKind, ...] = (
    SOFTWARE_ENGINEER_V1,
    SOFTWARE_ENGINEER_V2,
    SOFTWARE_ENGINEER_V3,
    SOFTWARE_ENGINEER_V4,
    SOFTWARE_ENGINEER_V5,
    SOFTWARE_ENGINEER_V6,
    SOFTWARE_ENGINEER_V7,
    SOFTWARE_ENGINEER_KIND,
    ANALYSIS_V1,
    ANALYSIS_V2,
    ANALYSIS_V3,
    ANALYSIS_KIND,
    PLANNER_KIND,
    PLATFORM_ASSISTANT_V1,
    PLATFORM_ASSISTANT_KIND,
    REVIEWER_KIND,
    OPS_ANALYST_KIND,
)
"""Every kind the platform ships, at every version it still runs."""


class ValidationWorkKind(StrEnum):
    """The names of the validation session's kinds of work."""

    VALIDATION = "VALIDATION"  # a validation session's check, on a fresh executor


class ValidationPayload(OmBase):
    """The VALIDATION kind carries nothing: its target is the validation
    session, which holds what it runs."""


VALIDATION_WORK_KINDS: tuple[WorkKindSpec, ...] = (
    # A validation session's start asks for it, relayed from its own commit;
    # the run writes the session's validation and finishes the session,
    # which WRITE covers. It runs on the platform's own worker, with no
    # agent and no model call.
    WorkKindSpec(ValidationWorkKind.VALIDATION, ValidationPayload, Permission.WRITE),
)
"""The validation session's kind, registered below the marker of
`root.KINDS`."""
