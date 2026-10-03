"""Pure rules of the agents a platform ships: the platform assistant's
reach, an edit of one place in a file, the matches a search of the code
answers, the corpus the knowledge map lists for one audience, a search of
it, and a draft of the tenant's tool policy against what is live. Values
in, values out."""

import re
from collections.abc import Collection, Iterable, Mapping
from pathlib import PurePosixPath
from typing import NamedTuple

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


# An edit of one place in a file.

MOST_COUNTED = 100
"""The most places a refused match counts before it says "at least"."""


class Edit(NamedTuple):
    """A text with one place replaced: the new text, the line the place
    starts on, and how many lines the new text holds there."""

    text: str
    line: int
    lines: int


def lines_of(text: str) -> list[str]:
    """The lines of a text, each with its own end, counted as a search counts
    them: a line ends at a newline."""
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def edited(
    text: str,
    new_text: str,
    *,
    old_text: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
) -> Edit | str:
    """The text with one place replaced by `new_text`. The place is
    `old_text` where it matches exactly one place, overlapping matches
    counted, or the lines `start_line` to `end_line`, counted from 1, both
    included; a new text that drops the range's last line end keeps it.
    Why it cannot land, in words the model reads, for a match of no place
    or of more than one, and for a range past the text's end."""
    if old_text is not None:
        start = text.find(old_text)
        if start < 0:
            return "old_text matches no place in the file: read it again, and copy it"
        found, at = 1, text.find(old_text, start + 1)
        while at >= 0 and found < MOST_COUNTED:
            found, at = found + 1, text.find(old_text, at + 1)
        if found > 1:
            places = f"{found}" if at < 0 else f"at least {found}"
            return (
                f"old_text matches {places} places in the file, and an edit changes one: "
                "give more of the text around it, so it matches one place"
            )
        end, replacement = start + len(old_text), new_text
    else:
        assert start_line is not None and end_line is not None
        lines = lines_of(text)
        if end_line > len(lines):
            return f"the file has {len(lines)} lines, and the range ends at {end_line}"
        start = sum(len(line) for line in lines[: start_line - 1])
        end = start + sum(len(line) for line in lines[start_line - 1 : end_line])
        last = lines[end_line - 1]
        replacement = new_text
        if new_text and not new_text.endswith("\n") and last.endswith("\n"):
            replacement += "\r\n" if last.endswith("\r\n") else "\n"
    line = text.count("\n", 0, start) + 1
    return Edit(text[:start] + replacement + text[end:], line, len(lines_of(replacement)))


# The matches of a search of the code.


def matches_of(output: str, limit: int, width: int) -> tuple[list[tuple[str, int, str]], bool]:
    """The matches in what a recursive search printed, one a line as
    `path NUL line:text`: each as its path inside the workspace, its line,
    and its text cut at `width` characters, at most `limit` of them; and
    whether more were printed. A line of another shape, such as the mark
    where a bounded output was cut, is no match."""
    found: list[tuple[str, int, str]] = []
    for row in output.split("\n"):
        path, nul, rest = row.partition("\0")
        number, colon, matched = rest.partition(":")
        if not (nul and colon and path and number.isdigit()):
            continue
        if len(found) == limit:
            return found, True
        path = path.removeprefix("./")
        found.append((path, int(number), matched.rstrip("\r")[:width]))
    return found, False


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
