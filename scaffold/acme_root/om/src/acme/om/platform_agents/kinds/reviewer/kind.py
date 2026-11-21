"""The reviewer: it reads one pull request through the forge, at its head,
notes each finding with its file, its line, and its grade, and submits its
review through its result tool, citing them. Its prompt is
`prompts/v1.md`."""

from acme.om.agent_sessions.limits import Limits
from acme.om.agents.prompts import prompt_of
from acme.om.agents.types.kind import NO_AGENT_WORKSPACE, AgentKind, DoneRule
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.platform_agents.kinds import (
    AGENT_KNOWLEDGE_TOOLSET,
    CACHED_CALL_MICROS,
    COMMENT,
    REVIEW_TOOLSET,
    REVIEWER,
    REVIEWER_ASKS,
    SPAWNED,
    SUBMIT_REVIEW,
    TOOL_OUTPUTS_TOOLSET,
    XL_CALL_FACTOR,
    allowing,
)
from acme.om.spend_budgets.types.amount import Amount
from acme.om.tools.types.tool import ToolClass

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
    prompts=(prompt_of(__file__, 1),),
    policy=allowing(ToolClass.READ),
    isolation=NO_AGENT_WORKSPACE,
    share=REVIEWER_SHARE,
    started_by=SPAWNED,
)
"""The reviewer. It reads one pull request through the forge, at its head,
and changes nothing: it has no workspace, and no tool it holds writes a
file, runs code, or pushes. It delivers its review through its result
tool, citing the findings it noted. It names an agent among those who
may start it, and a share, so a lead starts it as a sub-agent on the pull
request another kind opened."""

VERSIONS = (REVIEWER_KIND,)
"""Every version of the reviewer the platform still runs."""
