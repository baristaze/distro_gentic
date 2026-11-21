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
  as names its share and an agent among those who may start it
  (`SPAWNED`, ADR 2043).
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

Each kind is a folder of its own beside the others, `<kind>/`: its
`kind.py` holds a constant for each version and `VERSIONS`, every version
the platform still runs, and its `prompts/` the prompt of each version,
pinned in its lock (`acme.om.agents.prompts`). Beside them, `manuals/` and
`wiki/` hold the texts the kind ships for its sessions
(`platform_agents.folders`). The platform's catalog joins the folders
(`platform_agents.shipped`).

This module holds what the kinds share. Every kind is built from the
platform's toolsets (`TOOLSETS`), with a few tools named alone where a
toolset would give it more than it may call. It asks a model size of each
model role it calls (`ASKS`), and carries its warm grace (`GRACES`): how
long its workspace stays held after a loop for a follow-up.

A validation session is not here: it runs a check with no agent at all
(`types/validation.py`). Nothing routes a message to one kind or another:
a person chooses by choosing the session they type in."""

from collections.abc import Mapping
from datetime import timedelta
from enum import StrEnum
from typing import Any

from acme.infra.agent_workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.om.agents.types.kind import AgentKind, Starter
from acme.om.base import OmBase
from acme.om.context import Permission
from acme.om.language_models.types.fill import MAIN, SUMMARIZER, ModelAsk, ModelSize
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


SPAWNED: frozenset[Starter] = frozenset({Starter.PERSON, Starter.AGENT})
"""Who may start a kind a spawn starts: a person, and an agent as its
sub-agent. The software engineer from version 3, analysis from version 3,
and the reviewer name it beside their share."""

BY_A_PERSON: frozenset[Starter] = frozenset({Starter.PERSON})
"""Who may start every other shipped kind: a person alone, so a spawn of
it is refused."""


def allowing(*classes: ToolClass) -> ToolPolicyLayer:
    """A kind's layer of policy: these classes run unattended. A tenant
    narrows or loosens it, and the platform's ceilings hold above both."""
    return ToolPolicyLayer(
        rules=tuple(ToolPolicyRule(authorization_class=c, decision=Decision.ALLOW) for c in classes)
    )


CACHED_CALL_MICROS = 100_000
"""What one call of the main role over a cached window costs at list price,
as each share counts it: a choice."""

XL_CALL_FACTOR = 2
"""What one call of a main role at XL costs against one at L, at the list
prices of the models the two sizes run on: twice. A choice."""

WORKSPACE_BASE_KINDS: frozenset[tuple[str, int]] = frozenset({(SOFTWARE_ENGINEER, 8)})
"""The platform's kinds, by name and version, whose workspace starts from
the workspace base its session's agent project names: the software engineer from version 8.
A later version that takes it joins here; the versions before it keep
their own base. A product names its own beside these, in its slot
(`platform_root.ProductKinds.workspace_bases`)."""


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
