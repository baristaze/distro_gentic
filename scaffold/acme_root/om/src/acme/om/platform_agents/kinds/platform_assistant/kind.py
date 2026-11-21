"""The platform assistant: it answers the people who run their part of the
platform, on their own permissions, from the corpus, the agent knowledge
base, and the tenant's live records; it drafts configuration a person
applies, and hands engineering work to a software engineer. It has no
workspace, repository, or shell. Each version's prompt is
`prompts/v<N>.md`, and `object_model.md` the prompt its current version
takes after its own when a product names its section of the object
model."""

from pathlib import Path

from acme.om.agents.prompts import prompt_of
from acme.om.agents.types.kind import NO_AGENT_WORKSPACE, AgentKind, DoneRule
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.platform_agents.kinds import (
    AGENT_KNOWLEDGE_TOOLSET,
    ASKS,
    BY_A_PERSON,
    DRAFT_TOOL_POLICY,
    HANDOFF_TOOLSET,
    PLATFORM_ASSISTANT,
    READ_AGENT_SESSION,
    RECORDS_TOOLSET,
    SEARCH_CORPUS,
    allowing,
)
from acme.om.tools.types.tool import ToolClass

PLATFORM_ASSISTANT_V1 = AgentKind(
    name=PLATFORM_ASSISTANT,
    version=1,
    tools=(SEARCH_CORPUS, READ_AGENT_SESSION, DRAFT_TOOL_POLICY),
    toolsets=(HANDOFF_TOOLSET,),
    asks=ASKS,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    prompts=(prompt_of(__file__, 1),),
    policy=allowing(ToolClass.READ, ToolClass.SPAWN),
    isolation=NO_AGENT_WORKSPACE,
    started_by=BY_A_PERSON,
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
    prompts=(prompt_of(__file__, 2),),
    policy=allowing(ToolClass.READ, ToolClass.SPAWN),
    isolation=NO_AGENT_WORKSPACE,
    started_by=BY_A_PERSON,
)
"""The platform assistant. A product adds its own readers to it through its
slot (`ProductKinds.assistant_tools`), and names the document of its own
section of the object model there (`ProductKinds.object_model`); the root
joins both to this version alone."""

PRODUCT_OBJECT_MODEL = (
    (Path(__file__).parent / "object_model.md").read_text(encoding="utf-8").removesuffix("\n")
)
"""The prompt the platform assistant's current version takes after its own
when a product names its section of the object model, `{path}` that
document's path in the knowledge map."""

VERSIONS = (PLATFORM_ASSISTANT_V1, PLATFORM_ASSISTANT_KIND)
"""Every version of the platform assistant the platform still runs."""
