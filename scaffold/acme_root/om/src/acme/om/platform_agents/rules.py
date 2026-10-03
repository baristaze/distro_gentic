"""Pure rules of the agents a platform ships: the platform assistant's
reach, the corpus the knowledge map lists for one audience, a search of
it, and a draft of the tenant's tool policy against what is live. Values
in, values out."""

import re
from collections.abc import Collection, Iterable, Mapping
from pathlib import PurePosixPath

from acme.infra.workspaces import IsolationMode
from acme.om.agents.types.kind import AgentKind
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.platform_agents.types.corpus import Corpus, Document, Listing, Passage
from acme.om.platform_agents.types.draft import PolicyDraft
from acme.om.tools.types.policy import ApproverRule, PolicyRule, ToolPolicy
from acme.om.tools.types.tool import ToolClass

# The assistant's reach.

ASSISTANT_CLASSES: frozenset[str] = frozenset({ToolClass.READ, ToolClass.SPAWN})
"""The only classes of call the platform assistant makes: it reads, and it
hands work to an engineer. A tool that writes, runs code, reaches a bound
system such as a repository, or changes configuration or credentials is of
another class, so no profile of the assistant holds one."""


def reach_refusal(kind: AgentKind, classes: Mapping[str, str]) -> str | None:
    """Why a profile of the platform assistant reaches past what it may, or
    None when it does not. `classes` is the class of every tool the catalog
    holds, by name. Its authority is delegated, it has no workspace, and
    every tool it names is one the catalog holds, of a class it may make."""
    if kind.authority is not AuthorityMode.DELEGATED:
        return f"{kind.name} v{kind.version}: the assistant's authority is delegated"
    if kind.isolation.mode is not IsolationMode.NONE:
        return f"{kind.name} v{kind.version}: the assistant has no workspace"
    for tool in kind.tools:
        found = classes.get(tool)
        if found is None:
            return f"{kind.name} v{kind.version}: {tool} is not a tool the catalog holds"
        if found not in ASSISTANT_CLASSES:
            return (
                f"{kind.name} v{kind.version}: {tool} is a {found} tool, and the assistant "
                f"only reads and hands work on"
            )
    return None


# The knowledge map.

TENANT_USERS = "Tenant users and admins"
"""The knowledge map's section of what the tenant's own users are served:
the assistant's corpus, and the only one."""

LISTED = re.compile(r"^- \[(?P<title>[^\]]+)\]\((?P<path>[^)\s]+)\)")
"""A line of the map: `- [Title](path): what it holds`."""


def local_path(path: str) -> bool:
    """Whether a listed path names a document of this repository: relative,
    with no scheme, no fragment, and no step out of the map's folder."""
    if ":" in path or "#" in path or path.startswith("/"):
        return False
    return ".." not in PurePosixPath(path).parts


def listed(knowledge_map: str, audience: str) -> tuple[Listing, ...]:
    """The documents the map lists under `audience`'s section, in its order,
    each once. A document is served by being listed there, never by its
    folder, so a document listed only for another audience is not here."""
    found: dict[str, Listing] = {}
    inside = False
    for line in knowledge_map.splitlines():
        if line.startswith("#"):
            inside = line.startswith("## ") and line[3:].strip() == audience
            continue
        match = LISTED.match(line) if inside else None
        if match is not None and local_path(match["path"]):
            found.setdefault(match["path"], Listing(title=match["title"], path=match["path"]))
    return tuple(found.values())


# Search.

WORD = re.compile(r"[a-z0-9]+")
STOP = frozenset({"the", "and", "for", "what", "how", "why", "who", "does", "with", "this"})


def words(text: str) -> list[str]:
    return [word for word in WORD.findall(text.lower()) if len(word) > 2 and word not in STOP]


def sections(document: Document) -> tuple[Passage, ...]:
    """A document cut at its headings: each passage is the text under one
    heading, cited by the document's path and that heading."""
    passages: list[Passage] = []
    heading = document.title
    lines: list[str] = []

    def close() -> None:
        text = "\n".join(lines).strip()
        if text:
            passages.append(
                Passage(path=document.path, title=document.title, heading=heading, text=text)
            )

    for line in document.text.splitlines():
        if line.startswith("#"):
            close()
            heading, lines = line.lstrip("#").strip() or document.title, []
        else:
            lines.append(line)
    close()
    return tuple(passages)


def search(corpus: Corpus, query: str, limit: int) -> tuple[Passage, ...]:
    """The passages of the corpus that share the most of the query's words,
    best first, at most `limit`. A passage that shares none is never an
    answer."""
    asked = set(words(query))
    scored: list[tuple[int, int, int, Passage]] = []
    for document in corpus.documents:
        for passage in sections(document):
            held = words(f"{passage.heading} {passage.text}")
            shared = asked.intersection(held)
            if shared:
                hits = sum(1 for word in held if word in asked)
                scored.append((-len(shared), -hits, len(scored), passage))
    scored.sort(key=lambda entry: entry[:3])
    return tuple(entry[3] for entry in scored[:limit])


# A draft of the tenant's tool policy.


def draft_problems(
    rules: Iterable[PolicyRule],
    approvers: Iterable[ApproverRule],
    tools: Collection[str],
    classes: Collection[str],
) -> tuple[str, ...]:
    """What makes a draft one that cannot hold as written: a rule or an
    approver that names a tool or a class the platform does not have, which
    would match no call, and a class with two approver rules."""
    problems: list[str] = []
    for rule in rules:
        if rule.tool is not None and rule.tool not in tools:
            problems.append(f"a rule names the tool {rule.tool}, which no agent here has")
        if rule.authorization_class is not None and rule.authorization_class not in classes:
            problems.append(f"a rule names the class {rule.authorization_class}, which is unknown")
    seen: set[str] = set()
    for approver in approvers:
        if approver.authorization_class not in classes:
            problems.append(
                f"an approver rule names the class {approver.authorization_class}, which is unknown"
            )
        if approver.authorization_class in seen:
            problems.append(f"the class {approver.authorization_class} has two approver rules")
        seen.add(approver.authorization_class)
    return tuple(problems)


def draft_policy(
    live: ToolPolicy,
    rules: tuple[PolicyRule, ...],
    approvers: tuple[ApproverRule, ...],
    tools: Collection[str],
    classes: Collection[str],
) -> PolicyDraft:
    """A draft against the live policy: its problems, the rules it adds and
    the ones it takes away, and the approvers before and after. It names
    the live version, which the write that applies it must name too."""
    problems = draft_problems(rules, approvers, tools, classes)
    return PolicyDraft(
        based_on=live.version,
        valid=not problems,
        problems=problems,
        added=tuple(rule for rule in rules if rule not in live.rules),
        removed=tuple(rule for rule in live.rules if rule not in rules),
        approvers_before=live.approvers,
        approvers_after=approvers,
        rules=rules,
    )
