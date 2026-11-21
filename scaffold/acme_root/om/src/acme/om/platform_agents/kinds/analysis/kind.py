"""Analysis: it reads what a run produced in a workspace, searches it and
the agent knowledge base, changes nothing, and answers with findings. Each
version's prompt is `prompts/v<N>.md`."""

from acme.om.agent_sessions.limits import Limits
from acme.om.agents.prompts import prompt_of
from acme.om.agents.types.kind import AgentKind, DoneRule
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.platform_agents.kinds import (
    AGENT_KNOWLEDGE_TOOLSET,
    ANALYSIS,
    ASKS,
    BY_A_PERSON,
    CACHED_CALL_MICROS,
    FILES_TOOLSET,
    LIST_FILES,
    READ_FILE,
    RUN_COMMAND,
    SPAWNED,
    SUB_AGENTS_TOOLSET,
    TOOL_OUTPUTS_TOOLSET,
    WORKSPACE,
    allowing,
    revised,
)
from acme.om.spend_budgets.types.amount import Amount
from acme.om.tools.types.tool import ToolClass

ANALYSIS_V1 = AgentKind(
    name=ANALYSIS,
    version=1,
    tools=(LIST_FILES, READ_FILE, RUN_COMMAND),
    asks=ASKS,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.STEADY,
    prompts=(prompt_of(__file__, 1),),
    policy=allowing(ToolClass.READ, ToolClass.EXECUTE),
    isolation=WORKSPACE,
    started_by=BY_A_PERSON,
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
    prompts=(prompt_of(__file__, 2),),
    policy=allowing(ToolClass.READ, ToolClass.EXECUTE),
    isolation=WORKSPACE,
    started_by=BY_A_PERSON,
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

ANALYSIS_V3 = revised(
    ANALYSIS_V2,
    version=3,
    toolsets=(*ANALYSIS_V2.toolsets, SUB_AGENTS_TOOLSET),
    # Its prompt adds when to start a sub-agent, and that it waits for
    # every report before it answers, since a turn that calls no tool is
    # its answer.
    prompts=(prompt_of(__file__, 3),),
    policy=allowing(ToolClass.READ, ToolClass.EXECUTE, ToolClass.SPAWN),
    share=ANALYSIS_SHARE,
    started_by=SPAWNED,
)
"""Analysis before it read back a result kept outside its window: kept
while a session may still run it."""

ANALYSIS_KIND = revised(
    ANALYSIS_V3,
    version=4,
    toolsets=(*ANALYSIS_V3.toolsets, TOOL_OUTPUTS_TOOLSET),
    prompts=(prompt_of(__file__, 4),),
)
"""Analysis. It starts sub-agents of its own, and a spawn may start it, the
way a software engineer splits a question, so it names an agent among those
who may start it, and a share. A result too large for its window, or one
compaction elided, it reads back with `read_tool_output`, by the handle the
notice names."""

VERSIONS = (ANALYSIS_V1, ANALYSIS_V2, ANALYSIS_V3, ANALYSIS_KIND)
"""Every version of analysis the platform still runs."""
