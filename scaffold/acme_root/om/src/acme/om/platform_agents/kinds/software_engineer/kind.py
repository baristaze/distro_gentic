"""The software engineer: it takes an objective to a validated, reviewable
change in a workspace of its own, and ends through the result gate, citing
the runs that validated its head. Each version's prompt is
`prompts/v<N>.md`."""

from acme.om.agent_sessions.limits import Limits
from acme.om.agents.prompts import prompt_of
from acme.om.agents.types.kind import AgentKind, DoneRule
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.platform_agents.kinds import (
    AGENT_KNOWLEDGE_TOOLSET,
    ASKS,
    BY_A_PERSON,
    CACHED_CALL_MICROS,
    CODE_TOOLSET,
    FILES_TOOLSET,
    LIST_FILES,
    READ_FILE,
    RUN_COMMAND,
    SOFTWARE_ENGINEER,
    SPAWNED,
    SUB_AGENTS_TOOLSET,
    SUBMIT_RESULT,
    SUGGEST_AGENT_KNOWLEDGE,
    TOOL_OUTPUTS_TOOLSET,
    WORK_PRODUCT_TOOLSET,
    WORKSPACE,
    WRITE_FILE,
    allowing,
    revised,
)
from acme.om.spend_budgets.types.amount import Amount
from acme.om.tools.types.tool import ToolClass

SOFTWARE_ENGINEER_V1 = AgentKind(
    name=SOFTWARE_ENGINEER,
    version=1,
    tools=(LIST_FILES, READ_FILE, WRITE_FILE, RUN_COMMAND),
    toolsets=(WORK_PRODUCT_TOOLSET,),
    asks=ASKS,
    done_rule=DoneRule.RESULT_TOOL,
    result_tool=SUBMIT_RESULT,
    authority=AuthorityMode.STEADY,
    prompts=(prompt_of(__file__, 1),),
    # Its pull request is its own work product, so it opens without asking.
    policy=allowing(ToolClass.READ, ToolClass.WRITE, ToolClass.EXECUTE, ToolClass.INTEGRATION),
    isolation=WORKSPACE,
    started_by=BY_A_PERSON,
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
    prompts=(prompt_of(__file__, 2),),
    # Its pull request is its own work product, so it opens without asking.
    policy=allowing(ToolClass.READ, ToolClass.WRITE, ToolClass.EXECUTE, ToolClass.INTEGRATION),
    isolation=WORKSPACE,
    started_by=BY_A_PERSON,
)
"""The software engineer before it named a share: kept while a session may still run
it."""

SOFTWARE_ENGINEER_V3 = SOFTWARE_ENGINEER_V2.model_copy(
    update={
        "version": 3,
        "prompts": (prompt_of(__file__, 3),),
        "share": Amount(cost_micros=50_000_000),
        "started_by": SPAWNED,
    }
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
        "prompts": (prompt_of(__file__, 4),),
        "share": SOFTWARE_ENGINEER_SHARE,
        "limits": Limits(step_guard=SOFTWARE_ENGINEER_STEP_GUARD),
    }
)
"""The software engineer before it started sub-agents: kept while a session may
still run it."""

SOFTWARE_ENGINEER_V5 = revised(
    SOFTWARE_ENGINEER_V4,
    version=5,
    toolsets=(*SOFTWARE_ENGINEER_V4.toolsets, SUB_AGENTS_TOOLSET),
    # Its prompt adds when to start a sub-agent, and that a question which
    # only reads or checks runs as analysis, under analysis's share.
    prompts=(prompt_of(__file__, 5),),
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

SOFTWARE_ENGINEER_V6 = SOFTWARE_ENGINEER_V5.model_copy(
    # Its prompt adds a baseline again on a base that moves, so feedback
    # after its pull request merged, on a branch cut again, can still end
    # in a success.
    update={"version": 6, "prompts": (prompt_of(__file__, 6),)}
)
"""The software engineer before it read back a result kept outside its window:
kept while a session may still run it."""

SOFTWARE_ENGINEER_V7 = revised(
    SOFTWARE_ENGINEER_V6,
    version=7,
    toolsets=(*SOFTWARE_ENGINEER_V6.toolsets, TOOL_OUTPUTS_TOOLSET),
    prompts=(prompt_of(__file__, 7),),
)
"""The software engineer before its workspace started from its agent project's
workspace base: kept while a session may still run it."""

SOFTWARE_ENGINEER_KIND = SOFTWARE_ENGINEER_V7.model_copy(
    # Its prompt adds that its workspace has no network, so a missing
    # package is named rather than fetched.
    update={"version": 8, "prompts": (prompt_of(__file__, 8),)}
)
"""The software engineer. It starts sub-agents and waits on them, and since it
delivers through its result tool, a product's kind may spawn it too, under
its share. A result too large for its window, or one compaction elided, it
reads back with `read_tool_output`, by the handle the notice names. Its
workspace starts from its agent project's workspace base, when the agent project names
one, and keeps no egress (`WORKSPACE_BASE_KINDS`)."""

VERSIONS = (
    SOFTWARE_ENGINEER_V1,
    SOFTWARE_ENGINEER_V2,
    SOFTWARE_ENGINEER_V3,
    SOFTWARE_ENGINEER_V4,
    SOFTWARE_ENGINEER_V5,
    SOFTWARE_ENGINEER_V6,
    SOFTWARE_ENGINEER_V7,
    SOFTWARE_ENGINEER_KIND,
)
"""Every version of the software engineer the platform still runs."""
