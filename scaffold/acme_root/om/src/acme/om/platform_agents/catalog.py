"""The shipped agents as a root wires them: the kinds, the tools they call
beside the adopter's, a product's own readers joined to the platform
assistant, and the refusal, at boot, of a catalog that would let the
platform assistant reach past what it may. A process hands its root a
`PlatformAgents`, which carries the assistant's corpus, read once at boot
from the knowledge map (`read_corpus`)."""

from collections.abc import Callable, Iterable
from pathlib import Path

from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agents import AgentsManagerInterface
from acme.om.agents.types.kind import AgentKind
from acme.om.automations import AutomationsManagerInterface
from acme.om.base import Platform
from acme.om.evidence import EvidenceManagerInterface
from acme.om.exceptions import UnsafeConfiguration
from acme.om.hosts import HostsManagerInterface
from acme.om.intake import IntakeManagerInterface
from acme.om.knowledge import KnowledgeManagerInterface
from acme.om.platform_agents import kinds, rules
from acme.om.platform_agents.tools import (
    DraftToolPolicyImpl,
    EditFileImpl,
    HandOffToEngineerImpl,
    ListAutomationsImpl,
    ListFilesImpl,
    ListProjectsImpl,
    ListSessionsImpl,
    OpenPullRequestImpl,
    ReadAutomationImpl,
    ReadFileImpl,
    ReadKnowledgeImpl,
    ReadProjectImpl,
    ReadSessionImpl,
    ReadWaitImpl,
    RunCommandImpl,
    SearchCodeImpl,
    SearchCorpusImpl,
    SearchKnowledgeImpl,
    SubmitResultImpl,
    SuggestKnowledgeImpl,
    ValidateImpl,
    WriteFileImpl,
)
from acme.om.platform_agents.types.corpus import Corpus, Document
from acme.om.projects import ProjectsManagerInterface
from acme.om.relay import RelayManagerInterface
from acme.om.steps import StepsManagerInterface
from acme.om.tools import ToolsManagerInterface
from acme.om.tools.tool import ToolInterface
from acme.om.tools.types.tool import ToolClass
from acme.om.work import WorkManagerInterface
from acme.om.workspaces import WorkspacesManagerInterface

KNOWLEDGE_MAP = "llms.txt"


class PlatformAgents(Platform):
    """What a process hands its root to ship the platform's agents: the
    corpus the assistant answers from."""

    corpus: Corpus


def read_corpus(root: Path, audience: str = rules.TENANT_USERS) -> Corpus:
    """The documents the knowledge map at `root` lists for `audience`, read
    whole, once, at boot. A map or a listed document that is missing is an
    error, and so is a listed path that resolves outside `root`, a link
    included: a corpus is never quietly other than its map."""
    knowledge_map = (root / KNOWLEDGE_MAP).read_text()
    inside = root.resolve()
    documents: list[Document] = []
    for entry in rules.listed(knowledge_map, audience):
        path = (root / entry.path).resolve()
        if not path.is_relative_to(inside):
            raise ValueError(f"{entry.path} resolves outside {root}")
        documents.append(Document(title=entry.title, path=entry.path, text=path.read_text()))
    return Corpus(audience=audience, documents=tuple(documents))


def with_shipped(
    shipped: PlatformAgents,
    adopter: Iterable[ToolInterface],
    domain_classes: Iterable[str],
    *,
    sessions: Callable[[], AgentSessionsManagerInterface],
    steps: Callable[[], StepsManagerInterface],
    projects: Callable[[], ProjectsManagerInterface],
    work: Callable[[], WorkManagerInterface],
    hosts: Callable[[], HostsManagerInterface],
    relay: Callable[[], RelayManagerInterface],
    automations: Callable[[], AutomationsManagerInterface],
    policies: Callable[[], ToolsManagerInterface],
    agents: Callable[[], AgentsManagerInterface],
    evidence: Callable[[], EvidenceManagerInterface],
    workspaces: Callable[[], WorkspacesManagerInterface],
    intake: Callable[[], IntakeManagerInterface],
    knowledge: Callable[[], KnowledgeManagerInterface],
) -> tuple[ToolInterface, ...]:
    """The platform's tools, then the adopter's. The managers come late, as
    callables the root answers once it has built them; `intake`,
    `knowledge`, and `automations` are built over the managers, so the
    process that builds them answers them."""
    own_specs = (
        ListFilesImpl.SPEC,
        ReadFileImpl.SPEC,
        SearchCodeImpl.SPEC,
        EditFileImpl.SPEC,
        WriteFileImpl.SPEC,
        RunCommandImpl.SPEC,
        SearchKnowledgeImpl.SPEC,
        ReadKnowledgeImpl.SPEC,
        SuggestKnowledgeImpl.SPEC,
        ValidateImpl.SPEC,
        OpenPullRequestImpl.SPEC,
        SubmitResultImpl.SPEC,
        SearchCorpusImpl.SPEC,
        ReadSessionImpl.SPEC,
        ListSessionsImpl.SPEC,
        ReadWaitImpl.SPEC,
        ListProjectsImpl.SPEC,
        ReadProjectImpl.SPEC,
        ListAutomationsImpl.SPEC,
        ReadAutomationImpl.SPEC,
        DraftToolPolicyImpl.SPEC,
        HandOffToEngineerImpl.SPEC,
    )
    theirs = tuple(adopter)
    names = frozenset({spec.name for spec in own_specs} | {t.spec.name for t in theirs})
    classes = frozenset({*(c.value for c in ToolClass), *domain_classes})
    own: tuple[ToolInterface, ...] = (
        ListFilesImpl(),
        ReadFileImpl(),
        SearchCodeImpl(),
        EditFileImpl(evidence),
        WriteFileImpl(evidence),
        RunCommandImpl(),
        SearchKnowledgeImpl(shipped.corpus, knowledge),
        ReadKnowledgeImpl(shipped.corpus, knowledge),
        SuggestKnowledgeImpl(knowledge),
        ValidateImpl(evidence),
        OpenPullRequestImpl(workspaces, intake),
        SubmitResultImpl(),
        SearchCorpusImpl(shipped.corpus),
        ReadSessionImpl(sessions, steps, policies, projects),
        ListSessionsImpl(sessions, projects),
        ReadWaitImpl(sessions, work, hosts, relay),
        ListProjectsImpl(projects),
        ReadProjectImpl(projects),
        ListAutomationsImpl(automations),
        ReadAutomationImpl(automations),
        DraftToolPolicyImpl(policies, names, classes),
        HandOffToEngineerImpl(agents),
    )
    return (*own, *theirs)


def with_assistant_tools(
    agent_kinds: Iterable[AgentKind], extra: Iterable[str]
) -> tuple[AgentKind, ...]:
    """The kinds with a product's own tools added to the platform
    assistant's current version, the one a new session starts on; the
    versions before it keep what they named. A name the assistant already
    holds, or one named twice, is `UnsafeConfiguration`. A name no tool has,
    or a tool past what the assistant may call, is refused with the rest of
    its reach (`refuse_reach`)."""
    added = tuple(extra)
    if len(set(added)) != len(added):
        raise UnsafeConfiguration("the slot names one of the assistant's tools twice")
    current = kinds.PLATFORM_ASSISTANT_KIND
    taken = set(added) & set(current.tools)
    if taken:
        raise UnsafeConfiguration(
            f"the slot names {', '.join(sorted(taken))}, which the assistant already holds"
        )
    if not added:
        return tuple(agent_kinds)
    widened = current.model_copy(update={"tools": (*current.tools, *added)})
    return tuple(widened if kind == current else kind for kind in agent_kinds)


def refuse_reach(agent_kinds: Iterable[AgentKind], catalog: Iterable[ToolInterface]) -> None:
    """At boot, `UnsafeConfiguration` for a catalog that holds two tools of
    one name, since a registry could then hold either, or for a version of
    the platform assistant whose profile reaches past what it may
    (`rules.reach_refusal`)."""
    classes: dict[str, str] = {}
    for tool in catalog:
        if tool.spec.name in classes:
            raise UnsafeConfiguration(f"the catalog holds two tools named {tool.spec.name}")
        classes[tool.spec.name] = tool.spec.authorization_class
    for kind in agent_kinds:
        if kind.name != kinds.PLATFORM_ASSISTANT:
            continue
        refusal = rules.reach_refusal(kind, classes)
        if refusal is not None:
            raise UnsafeConfiguration(refusal)
