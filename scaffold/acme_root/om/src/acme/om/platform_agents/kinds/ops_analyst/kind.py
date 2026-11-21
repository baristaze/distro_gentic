"""The ops analyst: it reads the tenant's operations on its person's own
permissions, changes nothing, and leaves a fix it finds as an objective a
person hands to a software engineer. Its prompt is `prompts/v1.md`."""

from acme.om.agents.prompts import prompt_of
from acme.om.agents.types.kind import NO_AGENT_WORKSPACE, AgentKind, DoneRule
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.platform_agents.kinds import (
    AGENT_KNOWLEDGE_TOOLSET,
    ASKS,
    BY_A_PERSON,
    OPERATIONS_TOOLSET,
    OPS_ANALYST,
    RECORDS_TOOLSET,
    TOOL_OUTPUTS_TOOLSET,
    allowing,
)
from acme.om.tools.types.tool import ToolClass

OPS_ANALYST_KIND = AgentKind(
    name=OPS_ANALYST,
    version=1,
    toolsets=(RECORDS_TOOLSET, OPERATIONS_TOOLSET, AGENT_KNOWLEDGE_TOOLSET, TOOL_OUTPUTS_TOOLSET),
    asks=ASKS,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    prompts=(prompt_of(__file__, 1),),
    policy=allowing(ToolClass.READ),
    isolation=NO_AGENT_WORKSPACE,
    started_by=BY_A_PERSON,
)
"""The ops analyst. It reads the tenant's operations on its person's own
permissions: its sessions and what they wait on, its hosts and what they
offer, its budgets and their spend, its agent projects and agent automations. Every
tool it holds reads, so it changes nothing; a fix it finds leaves as an
objective a person hands to a software engineer."""

VERSIONS = (OPS_ANALYST_KIND,)
"""Every version of the ops analyst the platform still runs."""
