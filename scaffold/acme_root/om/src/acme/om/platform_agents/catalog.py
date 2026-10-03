"""The shipped agents as a root wires them: the kinds, the tools they call
beside the adopter's, and the refusal, at boot, of a catalog that would let
the platform assistant reach past what it may. A process hands its root a
`PlatformAgents`, which carries the assistant's corpus, read once at boot
from the knowledge map (`read_corpus`)."""

from collections.abc import Callable, Iterable
from pathlib import Path

from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agents import AgentsManagerInterface
from acme.om.agents.types.kind import AgentKind
from acme.om.base import Platform
from acme.om.evidence import EvidenceManagerInterface
from acme.om.exceptions import UnsafeConfiguration
from acme.om.platform_agents import kinds, rules
from acme.om.platform_agents.tools import (
    DraftToolPolicyImpl,
    HandOffToEngineerImpl,
    ListFilesImpl,
    ReadFileImpl,
    ReadSessionImpl,
    RunCommandImpl,
    SearchCorpusImpl,
    SubmitResultImpl,
    ValidateImpl,
    WriteFileImpl,
)
from acme.om.platform_agents.types.corpus import Corpus, Document
from acme.om.tools import ToolsManagerInterface
from acme.om.tools.tool import ToolInterface
from acme.om.tools.types.tool import ToolClass

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
    policies: Callable[[], ToolsManagerInterface],
    agents: Callable[[], AgentsManagerInterface],
    evidence: Callable[[], EvidenceManagerInterface],
) -> tuple[ToolInterface, ...]:
    """The platform's tools, then the adopter's. The managers come late, as
    callables the root answers once it has built them."""
    own_specs = (
        ListFilesImpl.SPEC,
        ReadFileImpl.SPEC,
        WriteFileImpl.SPEC,
        RunCommandImpl.SPEC,
        ValidateImpl.SPEC,
        SubmitResultImpl.SPEC,
        SearchCorpusImpl.SPEC,
        ReadSessionImpl.SPEC,
        DraftToolPolicyImpl.SPEC,
        HandOffToEngineerImpl.SPEC,
    )
    theirs = tuple(adopter)
    names = frozenset({spec.name for spec in own_specs} | {t.spec.name for t in theirs})
    classes = frozenset({*(c.value for c in ToolClass), *domain_classes})
    own: tuple[ToolInterface, ...] = (
        ListFilesImpl(),
        ReadFileImpl(),
        WriteFileImpl(evidence),
        RunCommandImpl(),
        ValidateImpl(evidence),
        SubmitResultImpl(),
        SearchCorpusImpl(shipped.corpus),
        ReadSessionImpl(sessions),
        DraftToolPolicyImpl(policies, names, classes),
        HandOffToEngineerImpl(agents),
    )
    return (*own, *theirs)


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
