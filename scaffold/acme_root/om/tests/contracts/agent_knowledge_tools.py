"""An agent's agent knowledge tools, run as the loop runs a call the gate let
through, in its session."""

import json
from pathlib import Path
from uuid import UUID

from acme.infra.agent_workspaces import AgentWorkspace
from acme.om.agent_steps.types.agent_step import AgentStep
from acme.om.agent_steps.types.header import ToolFailure
from acme.om.context import TenantContext
from acme.om.platform_agents.tools.agent_knowledge import (
    ReadAgentKnowledgeImpl,
    SearchAgentKnowledgeImpl,
    SuggestAgentKnowledgeImpl,
)
from acme.om.tools.tool import ToolInterface

from contracts.intake import Wired
from contracts.platform_agents import CORPUS
from contracts.tools import (
    Tools,
    failure_of,
    put_call,
    registry_of,
    result_text,
    tools_over,
    twin_transport,
)


class Asking:
    """The agent knowledge tools over the platform's agent knowledge and the corpus, and
    the tools manager that runs a call of one in a session."""

    def __init__(self, platform: Wired, tmp_path: Path) -> None:
        self.tools: Tools = tools_over(twin_transport(tmp_path)[0])
        self.search = SearchAgentKnowledgeImpl(CORPUS, lambda: platform.agent_knowledge)
        self.read = ReadAgentKnowledgeImpl(CORPUS, lambda: platform.agent_knowledge)
        self.suggest = SuggestAgentKnowledgeImpl(lambda: platform.agent_knowledge)

    async def call(
        self, ctx: TenantContext, agent_session_id: UUID, tool: ToolInterface, **call_input: object
    ) -> AgentStep:
        found = await put_call(
            self.tools.manager,
            self.tools.steps,
            ctx,
            tool.spec.name,
            dict(call_input),
            tool.spec.authorization_class,
            agent_session_id,
        )
        return await self.tools.manager.execute(
            ctx,
            registry_of(tool),
            found.request,
            found.call_input,
            AgentWorkspace.absent(ctx.org_id, agent_session_id),
            epoch=found.epoch,
            tree_deadline=None,
        )

    async def found(self, ctx: TenantContext, agent_session_id: UUID, query: str) -> set[str]:
        response = await self.call(ctx, agent_session_id, self.search, query=query, limit=10)
        assert failure_of(response) is None, result_text(response)
        return {
            f"{hit['scope']}:{hit['title']}" for hit in json.loads(result_text(response))["hits"]
        }

    async def text_of(
        self, ctx: TenantContext, agent_session_id: UUID, slug: str | None
    ) -> str | None:
        """The text a read of `slug` answers, or None when it is not found."""
        assert slug is not None
        response = await self.call(ctx, agent_session_id, self.read, slug=slug)
        if failure_of(response) is ToolFailure.PERMANENT:
            return None
        assert failure_of(response) is None, result_text(response)
        return json.loads(result_text(response))["text"]
