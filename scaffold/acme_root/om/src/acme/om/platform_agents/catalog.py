"""The shipped agents as a root wires them: the kinds, the tools they call
beside the adopter's, the forge's comment among them, a product's own
readers joined to the platform assistant, and the refusal, at boot, of a
catalog that would let the assistant, the ops analyst, or the reviewer
reach past what it may. A process hands its root a `PlatformAgents`,
which carries the assistant's corpus, read once at boot from the
knowledge map (`read_corpus`)."""

from collections.abc import Callable, Iterable
from pathlib import Path

from acme.integrations.events import IntegrationInterface
from acme.om.agent_automations import AgentAutomationsManagerInterface
from acme.om.agent_knowledge import AgentKnowledgeManagerInterface
from acme.om.agent_projects import AgentProjectsManagerInterface
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_workspaces import AgentWorkspacesManagerInterface
from acme.om.agents import AgentsManagerInterface
from acme.om.agents.types.kind import AgentKind
from acme.om.base import Platform
from acme.om.budgets import BudgetsManagerInterface
from acme.om.evidence import EvidenceManagerInterface
from acme.om.exceptions import UnsafeConfiguration
from acme.om.exec_relay import ExecRelayManagerInterface
from acme.om.hosts import HostsManagerInterface
from acme.om.intake import IntakeManagerInterface
from acme.om.intake.tools import COMMENT, CommentImpl
from acme.om.platform_agents import kinds, rules
from acme.om.platform_agents.tools import (
    DraftToolPolicyImpl,
    EditFileImpl,
    HandOffToSoftwareEngineerImpl,
    ListAgentAutomationsImpl,
    ListAgentProjectsImpl,
    ListFilesImpl,
    ListHostsImpl,
    ListSessionsImpl,
    NoteFindingImpl,
    OpenPullRequestImpl,
    ReadAgentAutomationImpl,
    ReadAgentKnowledgeImpl,
    ReadAgentProjectImpl,
    ReadFileImpl,
    ReadPullRequestFileImpl,
    ReadPullRequestImpl,
    ReadSessionImpl,
    ReadSpendImpl,
    ReadWaitImpl,
    RunCommandImpl,
    SearchAgentKnowledgeImpl,
    SearchCodeImpl,
    SearchCorpusImpl,
    SubmitResultImpl,
    SubmitReviewImpl,
    SuggestAgentKnowledgeImpl,
    ValidateImpl,
    WriteFileImpl,
)
from acme.om.platform_agents.types.corpus import Corpus, Document
from acme.om.steps import StepsManagerInterface
from acme.om.tools import ToolsManagerInterface
from acme.om.tools.tool import ToolInterface
from acme.om.tools.types.tool import ToolClass
from acme.om.work import WorkManagerInterface

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
    agent_projects: Callable[[], AgentProjectsManagerInterface],
    work: Callable[[], WorkManagerInterface],
    hosts: Callable[[], HostsManagerInterface],
    exec_relay: Callable[[], ExecRelayManagerInterface],
    agent_automations: Callable[[], AgentAutomationsManagerInterface],
    policies: Callable[[], ToolsManagerInterface],
    agents: Callable[[], AgentsManagerInterface],
    evidence: Callable[[], EvidenceManagerInterface],
    agent_workspaces: Callable[[], AgentWorkspacesManagerInterface],
    intake: Callable[[], IntakeManagerInterface],
    agent_knowledge: Callable[[], AgentKnowledgeManagerInterface],
    integrations: Callable[[str], IntegrationInterface],
    budgets: Callable[[], BudgetsManagerInterface],
) -> tuple[ToolInterface, ...]:
    """The platform's tools, then the adopter's. The managers come late, as
    callables the root answers once it has built them; `intake`,
    `agent_knowledge`, and `agent_automations` are built over the managers, so the
    process that builds them answers them. `integrations` answers the
    integration of a name, the forge's among them, which the reviewer's
    reads reach, and the forge's comment when the process wires none of its
    own."""
    own_specs = (
        ListFilesImpl.SPEC,
        ReadFileImpl.SPEC,
        SearchCodeImpl.SPEC,
        EditFileImpl.SPEC,
        WriteFileImpl.SPEC,
        RunCommandImpl.SPEC,
        SearchAgentKnowledgeImpl.SPEC,
        ReadAgentKnowledgeImpl.SPEC,
        SuggestAgentKnowledgeImpl.SPEC,
        ValidateImpl.SPEC,
        OpenPullRequestImpl.SPEC,
        SubmitResultImpl.SPEC,
        SearchCorpusImpl.SPEC,
        ReadSessionImpl.SPEC,
        ListSessionsImpl.SPEC,
        ReadWaitImpl.SPEC,
        ListAgentProjectsImpl.SPEC,
        ReadAgentProjectImpl.SPEC,
        ListAgentAutomationsImpl.SPEC,
        ReadAgentAutomationImpl.SPEC,
        DraftToolPolicyImpl.SPEC,
        HandOffToSoftwareEngineerImpl.SPEC,
        ReadPullRequestImpl.SPEC,
        ReadPullRequestFileImpl.SPEC,
        NoteFindingImpl.SPEC,
        SubmitReviewImpl.SPEC,
        ListHostsImpl.SPEC,
        ReadSpendImpl.SPEC,
    )
    theirs = tuple(adopter)
    names = frozenset({spec.name for spec in own_specs} | {COMMENT} | {t.spec.name for t in theirs})
    classes = frozenset({*(c.value for c in ToolClass), *domain_classes})
    own: tuple[ToolInterface, ...] = (
        ListFilesImpl(),
        ReadFileImpl(),
        SearchCodeImpl(),
        EditFileImpl(evidence),
        WriteFileImpl(evidence),
        RunCommandImpl(),
        SearchAgentKnowledgeImpl(shipped.corpus, agent_knowledge),
        ReadAgentKnowledgeImpl(shipped.corpus, agent_knowledge),
        SuggestAgentKnowledgeImpl(agent_knowledge),
        ValidateImpl(evidence),
        OpenPullRequestImpl(agent_workspaces, intake),
        SubmitResultImpl(),
        SearchCorpusImpl(shipped.corpus),
        ReadSessionImpl(sessions, steps, policies, agent_projects),
        ListSessionsImpl(sessions, agent_projects),
        ReadWaitImpl(sessions, work, hosts, exec_relay),
        ListAgentProjectsImpl(agent_projects),
        ReadAgentProjectImpl(agent_projects),
        ListAgentAutomationsImpl(agent_automations),
        ReadAgentAutomationImpl(agent_automations),
        DraftToolPolicyImpl(policies, names, classes),
        HandOffToSoftwareEngineerImpl(agents),
        ReadPullRequestImpl(intake, integrations),
        ReadPullRequestFileImpl(intake, integrations),
        NoteFindingImpl(intake, integrations),
        SubmitReviewImpl(),
        ListHostsImpl(hosts),
        ReadSpendImpl(budgets),
    )
    # The forge's comment, which the reviewer names, joins them unless the
    # process wires its own over the intake it builds.
    wired = any(tool.spec.name == COMMENT for tool in theirs)
    comment = () if wired else (CommentImpl(intake, integrations),)
    return (*own, *comment, *theirs)


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
    the platform assistant, the ops analyst, or the reviewer whose profile
    reaches past what it may, whoever declares it (`rules.reach_refusal`)."""
    classes: dict[str, str] = {}
    for tool in catalog:
        if tool.spec.name in classes:
            raise UnsafeConfiguration(f"the catalog holds two tools named {tool.spec.name}")
        classes[tool.spec.name] = tool.spec.authorization_class
    for kind in agent_kinds:
        refusal = rules.reach_refusal(kind, classes)
        if refusal is not None:
            raise UnsafeConfiguration(refusal)
