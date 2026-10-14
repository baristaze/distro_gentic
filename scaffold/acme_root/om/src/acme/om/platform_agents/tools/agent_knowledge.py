"""The `agent_knowledge` toolset: search and read the reviewed entries of
the session's agent project and of its whole tenant, and the platform's
own documentation, its corpus. The suggestion of an entry, which waits for
a person's review, and the assistant's search of the corpus sit here too."""

from collections.abc import Callable
from datetime import timedelta

from pydantic import Field

from acme.om.agent_knowledge import AgentKnowledgeManagerInterface
from acme.om.agent_knowledge.types.agent_knowledge import MAX_TEXT, AgentKnowledge
from acme.om.base import Platform
from acme.om.context import TenantContext
from acme.om.platform_agents import kinds, rules
from acme.om.platform_agents.tools.base import MAX_PATH, NativeToolImpl
from acme.om.platform_agents.types.corpus import Corpus, Passage
from acme.om.steps.types.content import MAX_NAME
from acme.om.tools.tool import ToolRuntime
from acme.om.tools.types.tool import Effect, ToolClass, ToolInput, ToolMode, ToolSpec

EXCERPT = 500  # characters of an entry or a passage a search answers

AGENT_PROJECT, TENANT, PLATFORM = "agent_project", "tenant", "platform"
"""Where a piece of agent knowledge comes from: an entry of the session's agent project,
one of its whole tenant, or the platform's own documentation."""


def scope_of(entry: AgentKnowledge) -> str:
    return TENANT if entry.agent_project_id is None else AGENT_PROJECT


class AgentKnowledgeQuery(ToolInput):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


class AgentKnowledgeHit(Platform):
    scope: str
    slug: str | None  # what read_agent_knowledge takes
    title: str
    heading: str | None = None  # the section of a platform document
    excerpt: str


class AgentKnowledgeHits(Platform):
    hits: tuple[AgentKnowledgeHit, ...]


class SearchAgentKnowledgeImpl(NativeToolImpl):
    """Searches what the session may know: the reviewed entries of its
    agent project and of its whole tenant, never another agent project's or another
    tenant's, and the platform's own documentation. An entry waiting for its
    review is never found. The session and its agent project are the call's,
    never the input's."""

    SPEC = ToolSpec(
        name=kinds.SEARCH_AGENT_KNOWLEDGE,
        description=(
            "Searches the agent knowledge base: the entries people of your team kept for your "
            "agent project and for the whole team, and the platform's documentation. Answers at "
            "most limit of each, best first, each with its scope, its slug, its title, and "
            "its opening. Read one whole with read_agent_knowledge and its slug."
        ),
        input_model=AgentKnowledgeQuery,
        output_model=AgentKnowledgeHits,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(
        self, corpus: Corpus, agent_knowledge: Callable[[], AgentKnowledgeManagerInterface]
    ) -> None:
        self._corpus = corpus
        self._agent_knowledge = agent_knowledge

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, AgentKnowledgeQuery)
        entries = await self._agent_knowledge().search(
            ctx, runtime.session_id, call_input.query, call_input.limit
        )
        passages = rules.search(self._corpus, call_input.query, call_input.limit)
        hits = [
            AgentKnowledgeHit(
                scope=scope_of(entry),
                slug=entry.slug,
                title=entry.title,
                excerpt=entry.text[:EXCERPT],
            )
            for entry in entries
        ]
        hits += [
            AgentKnowledgeHit(
                scope=PLATFORM,
                slug=passage.path,
                title=passage.title,
                heading=passage.heading,
                excerpt=passage.text[:EXCERPT],
            )
            for passage in passages
        ]
        return AgentKnowledgeHits(hits=tuple(hits))


class AgentKnowledgeSlug(ToolInput):
    slug: str = Field(min_length=1, max_length=MAX_PATH)


class AgentKnowledgeRead(Platform):
    scope: str
    slug: str
    title: str
    text: str


class ReadAgentKnowledgeImpl(NativeToolImpl):
    """Reads one piece of agent knowledge whole, by the slug a search answered: a
    document of the platform's corpus by its path, or a reviewed entry the
    session reaches. Any other entry is not found, as one that never existed
    is not."""

    SPEC = ToolSpec(
        name=kinds.READ_AGENT_KNOWLEDGE,
        description=(
            "Reads one piece of the agent knowledge base whole, by the slug search_agent_knowledge answered."
        ),
        input_model=AgentKnowledgeSlug,
        output_model=AgentKnowledgeRead,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(
        self, corpus: Corpus, agent_knowledge: Callable[[], AgentKnowledgeManagerInterface]
    ) -> None:
        self._corpus = corpus
        self._agent_knowledge = agent_knowledge

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, AgentKnowledgeSlug)
        slug = call_input.slug
        for document in self._corpus.documents:
            if document.path == slug:
                return AgentKnowledgeRead(
                    scope=PLATFORM, slug=slug, title=document.title, text=document.text
                )
        entry = await self._agent_knowledge().read(ctx, runtime.session_id, slug)
        return AgentKnowledgeRead(
            scope=scope_of(entry), slug=slug, title=entry.title, text=entry.text
        )


class SuggestionInput(ToolInput):
    title: str = Field(min_length=1, max_length=MAX_NAME)
    trigger: tuple[str, ...] = Field(min_length=1, max_length=20)
    text: str = Field(min_length=1, max_length=MAX_TEXT)


class Suggested(Platform):
    slug: str | None
    note: str


class SuggestAgentKnowledgeImpl(NativeToolImpl):
    """Suggests an entry for the session's agent project, or its whole tenant when
    it has none. It waits for a person's review, and no session recalls,
    finds, or reads it before. A repeat would suggest it twice, so a call
    whose run was lost is never run again."""

    SPEC = ToolSpec(
        name=kinds.SUGGEST_AGENT_KNOWLEDGE,
        description=(
            "Suggests an entry for the agent knowledge base: what a later session should not have "
            "to find out again, such as a procedure, a pitfall, or how a tool behaves here. "
            "Give it a title, the words that should bring it into a session that is about "
            "them, and its text. A person reviews it before any session reads it."
        ),
        input_model=SuggestionInput,
        output_model=Suggested,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.WRITE,
        effect=Effect.UNSAFE,
        interruptible=False,
        mode=ToolMode.SYNC,
    )

    def __init__(self, agent_knowledge: Callable[[], AgentKnowledgeManagerInterface]) -> None:
        self._agent_knowledge = agent_knowledge

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, SuggestionInput)
        entry = await self._agent_knowledge().suggest(
            ctx, runtime.session_id, call_input.title, call_input.trigger, call_input.text
        )
        return Suggested(slug=entry.slug, note="It waits for a person's review.")


class SearchInput(ToolInput):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


class Found(Platform):
    passages: tuple[Passage, ...]


class SearchCorpusImpl(NativeToolImpl):
    """Searches the corpus the root was given: what the knowledge map lists
    for the tenant's users, and nothing else."""

    SPEC = ToolSpec(
        name=kinds.SEARCH_CORPUS,
        description=(
            "Searches the product's documentation for the passages that answer a question. "
            "Each passage names the document and the heading it comes from: cite them."
        ),
        input_model=SearchInput,
        output_model=Found,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(self, corpus: Corpus) -> None:
        self._corpus = corpus

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, SearchInput)
        return Found(passages=rules.search(self._corpus, call_input.query, call_input.limit))
