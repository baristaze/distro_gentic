"""The agents a platform ships: profiles over the engine's one loop, each
with its own powers. A profile names its tools, its done rule, the
authority its calls run under, its workspace, and its layer of policy; the
engine runs every one of them the same way.

- The engineer takes an objective to a validated, reviewable change in a
  workspace of its own: it validates its committed head on a fresh
  executor, opens its pull request on its own branch, and ends through the
  result gate, citing those runs.
- Analysis reads what a run produced in a workspace, changes nothing, and
  answers with findings.
- The planner turns findings into tasks: it reads where sessions stand,
  hands new engineering work to an engineer, and answers with its plan.
- The platform assistant answers the people who run their part of the
  platform, on their own permissions: it reads the corpus and live state,
  drafts configuration a person applies, and hands engineering work to an
  engineer. It has no workspace, repository, or shell.

A validation session is not here: it runs a check with no agent at all
(`types/validation.py`). Nothing routes a message to one kind or another:
a person chooses by choosing the session they type in."""

from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.om.agents.types.kind import NO_WORKSPACE, AgentKind, DoneRule, TreeLimits
from acme.om.attribution.types.authority import AuthorityMode
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
RUN_COMMAND = "run_command"
SUBMIT_RESULT = "submit_result"
VALIDATE = "validate"
OPEN_PULL_REQUEST = "open_pull_request"
SEARCH_CORPUS = "search_corpus"
READ_SESSION = "read_session"
DRAFT_TOOL_POLICY = "draft_tool_policy"
HAND_OFF = "hand_off_to_engineer"

WORKSPACE = IsolationSpec(mode=IsolationMode.CONTAINER, egress=EgressPolicy(mode=EgressMode.NONE))
"""A container of its own, from which nothing leaves: the workspace of the
kinds that change or read files and run code."""


def allowing(*classes: ToolClass) -> PolicyLayer:
    """A kind's layer of policy: these classes run unattended. A tenant
    narrows or loosens it, and the platform's ceilings hold above both."""
    return PolicyLayer(
        rules=tuple(PolicyRule(authorization_class=c, decision=Decision.ALLOW) for c in classes)
    )


ENGINEER_KIND = AgentKind(
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
    tree=TreeLimits(height=1, count=0),
    prompts=(
        "You are an engineer. You take one objective to a validated, reviewable change "
        "in your workspace. Take a baseline with validate before you change anything. "
        "Change what the objective needs and nothing else, commit it, and validate the "
        "committed head. Open its pull request with open_pull_request, so a person can "
        "review it. Submit the result with submit_result, citing the runs validate "
        "answered: a success counts only when the validation at your head passed. A "
        "failure you explain with those runs is a result too.",
    ),
    # Its pull request is its own work product, so it opens without asking.
    policy=allowing(ToolClass.READ, ToolClass.WRITE, ToolClass.EXECUTE, ToolClass.INTEGRATION),
    isolation=WORKSPACE,
)

ANALYSIS_KIND = AgentKind(
    name=ANALYSIS,
    version=1,
    tools=(LIST_FILES, READ_FILE, RUN_COMMAND),
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.STEADY,
    tree=TreeLimits(height=1, count=0),
    prompts=(
        "You read what a run produced (its logs, its telemetry, its recordings) in your "
        "workspace, and turn it into findings. Change nothing. Answer with the findings, "
        "each citing the files and the commands that show it.",
    ),
    policy=allowing(ToolClass.READ, ToolClass.EXECUTE),
    isolation=WORKSPACE,
)

PLANNER_KIND = AgentKind(
    name=PLANNER,
    version=1,
    tools=(READ_SESSION, HAND_OFF),
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.STEADY,
    tree=TreeLimits(height=1, count=0),
    prompts=(
        "You turn findings into tasks. For each task, decide whether an existing session "
        "should continue it or a new one should start: read where a session stands with "
        "read_session, and hand new engineering work to an engineer with "
        "hand_off_to_engineer, with an objective that stands on its own. Answer with the "
        "plan: each task and the session it goes to.",
    ),
    policy=allowing(ToolClass.READ, ToolClass.SPAWN),
)

PLATFORM_ASSISTANT_KIND = AgentKind(
    name=PLATFORM_ASSISTANT,
    version=1,
    tools=(SEARCH_CORPUS, READ_SESSION, DRAFT_TOOL_POLICY, HAND_OFF),
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    tree=TreeLimits(height=1, count=0),
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

SHIPPED: tuple[AgentKind, ...] = (
    ENGINEER_KIND,
    ANALYSIS_KIND,
    PLANNER_KIND,
    PLATFORM_ASSISTANT_KIND,
)
"""Every kind the platform ships, at every version it still runs."""
