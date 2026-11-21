"""The support assistant: the kind behind the portal's support dock. It reads
what the platform assistant reads, on its person's own permissions, and
answers in the request that asks it (`RunsIn.REQUEST`), so the dock shows
its answer as it streams, with no queue and no claim before its first
token. It holds no workspace, starts no session, and makes no call that
waits for a person, within the engine's bounds of a request. Its prompt is
`prompts/v1.md`, and the platform assistant's `object_model.md` the prompt
its current version takes after its own when a product names its section
of the object model."""

from acme.om.agent_sessions.limits import Limits
from acme.om.agents.prompts import prompt_of
from acme.om.agents.types.kind import (
    NO_AGENT_WORKSPACE,
    REQUEST_STEPS,
    REQUEST_TIME,
    AgentKind,
    DoneRule,
    RunsIn,
)
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.platform_agents.kinds import (
    AGENT_KNOWLEDGE_TOOLSET,
    ASKS,
    BY_A_PERSON,
    DRAFT_TOOL_POLICY,
    RECORDS_TOOLSET,
    SEARCH_CORPUS,
    SUPPORT_ASSISTANT,
    TOOL_OUTPUTS_TOOLSET,
    allowing,
)
from acme.om.tools.types.tool import ToolClass

SUPPORT_ASSISTANT_KIND = AgentKind(
    name=SUPPORT_ASSISTANT,
    version=1,
    tools=(SEARCH_CORPUS, DRAFT_TOOL_POLICY),
    toolsets=(AGENT_KNOWLEDGE_TOOLSET, RECORDS_TOOLSET, TOOL_OUTPUTS_TOOLSET),
    asks=ASKS,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    prompts=(prompt_of(__file__, 1),),
    policy=allowing(ToolClass.READ),
    limits=Limits(step_guard=REQUEST_STEPS, run_time=REQUEST_TIME),
    isolation=NO_AGENT_WORKSPACE,
    runs_in=RunsIn.REQUEST,
    started_by=BY_A_PERSON,
)
"""The support assistant. It takes the platform assistant's readers whole
and leaves its hand-off out, since a request starts no session. A result too
long for its window, or elided once read, it reads back with
`read_tool_output`, by the handle the notice names: a request's loop keeps
it outside the window as a worker's does. A product's
readers (`ProductKinds.assistant_tools`) and its section of the object model
(`ProductKinds.object_model`) join this version as they join the
assistant's."""

VERSIONS = (SUPPORT_ASSISTANT_KIND,)
"""Every version of the support assistant the platform still runs."""
