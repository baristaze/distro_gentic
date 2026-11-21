"""The planner: it turns findings into tasks, reads where sessions stand,
hands new engineering work to a software engineer, and answers with its
plan. Its prompt is `prompts/v1.md`."""

from acme.om.agents.prompts import prompt_of
from acme.om.agents.types.kind import AgentKind, DoneRule
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.platform_agents.kinds import (
    ASKS,
    BY_A_PERSON,
    HANDOFF_TOOLSET,
    PLANNER,
    READ_AGENT_SESSION,
    allowing,
)
from acme.om.tools.types.tool import ToolClass

PLANNER_KIND = AgentKind(
    name=PLANNER,
    version=1,
    # It reads one session, never the tenant's other records.
    tools=(READ_AGENT_SESSION,),
    toolsets=(HANDOFF_TOOLSET,),
    asks=ASKS,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.STEADY,
    prompts=(prompt_of(__file__, 1),),
    policy=allowing(ToolClass.READ, ToolClass.SPAWN),
    started_by=BY_A_PERSON,
)

VERSIONS = (PLANNER_KIND,)
"""Every version of the planner the platform still runs."""
