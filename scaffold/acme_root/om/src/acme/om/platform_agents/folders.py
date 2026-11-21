"""What a kind's folder ships beside its module and its prompts. A kind is a
folder of its own, `kinds/<kind>/`, whose `kind.py` holds its versions and
`prompts/` their prompts (`acme.om.agents.prompts`). Beside them the
platform reads two folders of its own:

- `manuals/<name>.md`: the kind's own manuals. Each new session of the
  kind pins them, whole and in name order, at the start of its standing
  text, before the kind manual its tenant pinned and any text its maker
  sent, so they render in the system layer of every request
  (`impl/manuals.py`).
- `wiki/<slug>.md`: the kind's own agent knowledge. A header names its
  title and the words that trigger it, then its text follows. A session
  of the kind recalls an entry its subject triggers, and its agent
  searches and reads them by `<kind>/<slug>` (`agent_knowledge`).

Both are the kind's own, never a tenant's: no tenant writes, reviews,
edits, or erases them, and a session of another kind never reaches them.
A folder's texts are read when the platform's catalog, or a product's,
reads the folder (`folder_of`), and a text that cannot be read, or a
malformed one, refuses it. `folder_breaches` holds the rest, the lever
checks among them, in each gate that runs it."""

import re
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
from typing import cast

from pydantic import Field, ValidationError

from acme.om.agent_knowledge.types.agent_knowledge import MAX_SLUG, SLUG, KindEntry
from acme.om.agents.prompts import prompt_breaches
from acme.om.agents.types.kind import AgentKind
from acme.om.agents.types.request import MAX_STANDING
from acme.om.base import OmBase
from acme.om.exceptions import UnsafeConfiguration
from acme.om.levers.rules import checked
from acme.om.levers.types.lever import LeverReach

MANUALS = "manuals"
"""The folder beside a kind's module that holds its own manuals."""

WIKI = "wiki"
"""The folder beside a kind's module that holds its own agent knowledge."""

MAX_MANUALS = MAX_STANDING // 3
"""The most a kind's manuals hold together, in characters, as a session
receives them: a third of the standing text's bound, so the kind manual a
tenant pins and the standing text a maker sends keep the rest."""

NAME = re.compile(SLUG)
"""A manual's or an entry's file name, less `.md`: lowercase words joined
by single hyphens."""

HEADER = re.compile(r"\A---\n(?P<fields>(?:[a-z]+: [^\n]*\n)*)---\n\n?(?P<text>.*)\Z", re.DOTALL)
"""A wiki entry's file: its header between two `---` lines, one
`<field>: <value>` a line, then its text."""


class KindManual(OmBase):
    """One of a kind's own manuals: its name, its file's less `.md`, and its
    text, which a session receives whole."""

    name: str = Field(max_length=MAX_SLUG, pattern=SLUG)
    text: str = Field(min_length=1, max_length=MAX_MANUALS)


class KindFolder(OmBase):
    """A kind as its folder ships it: every version it still runs, its own
    manuals in name order, and its own agent knowledge."""

    versions: tuple[AgentKind, ...] = Field(min_length=1)
    manuals: tuple[KindManual, ...] = ()
    wiki: tuple[KindEntry, ...] = ()

    @property
    def name(self) -> str:
        return self.versions[0].name

    @property
    def manual(self) -> str:
        """The kind's manuals as a session receives them: each whole, in name
        order, a blank line between; empty when it ships none."""
        return "\n\n".join(manual.text for manual in self.manuals)


def folder_of(module: ModuleType) -> KindFolder:
    """The kind whose module, `kind.py` at its folder's root, is `module`:
    its `VERSIONS`, and the manuals and the wiki its folder ships. A module
    without its versions, a version of another kind than the folder's, a
    text that cannot be read, a malformed one, and manuals past
    `MAX_MANUALS` together are `UnsafeConfiguration`, naming the file."""
    folder = Path(str(module.__file__)).parent
    held: object = getattr(module, "VERSIONS", None)
    if not isinstance(held, tuple) or not held:
        raise UnsafeConfiguration(f"{folder.name}/kind.py: holds no VERSIONS")
    versions: list[AgentKind] = []
    for version in cast(tuple[object, ...], held):
        if not isinstance(version, AgentKind) or version.name != folder.name:
            raise UnsafeConfiguration(
                f"{folder.name}/kind.py: VERSIONS holds what is no version of {folder.name}"
            )
        versions.append(version)
    manuals, wiki, breaches = _texts(folder)
    if breaches:
        raise UnsafeConfiguration("; ".join(breaches))
    return KindFolder(versions=tuple(versions), manuals=manuals, wiki=wiki)


def folder_breaches(
    folder: Path, versions: Iterable[AgentKind], kinds: Iterable[str]
) -> tuple[str, ...]:
    """What the kind folder `folder` breaks, each breach naming its file: the
    engine's (`prompt_breaches`), then the platform's. A file in `manuals/`
    or `wiki/` that is no `<name>.md`; a text not UTF-8, empty, or past its
    bound, manuals past `MAX_MANUALS` together among them; an entry whose
    header is not its title and its trigger; and what the lever checks find
    in a manual or an entry, read against the tools of the kind's latest
    version and the names `kinds` of every kind there is. `versions` are
    the constants of the folder's module."""
    held = tuple(versions)
    latest = max(held, key=lambda kind: kind.version, default=None)
    reach = LeverReach(
        tools=frozenset(() if latest is None else latest.tools), kinds=frozenset(kinds)
    )
    manuals, wiki, breaches = _texts(folder)
    for manual in manuals:
        breaches.extend(_findings(folder / MANUALS / f"{manual.name}.md", manual.text, reach))
    for entry in wiki:
        text = f"{entry.title}\n{entry.text}"
        breaches.extend(_findings(folder / WIKI / f"{entry.slug}.md", text, reach))
    return (*prompt_breaches(folder, held), *breaches)


def _texts(folder: Path) -> tuple[tuple[KindManual, ...], tuple[KindEntry, ...], list[str]]:
    """The folder's manuals and entries that read, and why each that does not
    is refused."""
    breaches: list[str] = []
    manuals: list[KindManual] = []
    for path, text in _files(folder / MANUALS, breaches):
        try:
            manuals.append(KindManual(name=path.stem, text=text))
        except ValidationError:
            breaches.append(f"{_named(path)}: {len(text)} characters, past {MAX_MANUALS}")
    together = len("\n\n".join(manual.text for manual in manuals))
    if together > MAX_MANUALS:
        breaches.append(
            f"{folder.name}/{MANUALS}/: {together} characters together as a session receives "
            f"them, past {MAX_MANUALS}"
        )
    wiki: list[KindEntry] = []
    for path, text in _files(folder / WIKI, breaches):
        entry, refusal = _entry(folder.name, path, text)
        if entry is None:
            breaches.append(refusal)
        else:
            wiki.append(entry)
    return tuple(manuals), tuple(wiki), breaches


def _files(where: Path, breaches: list[str]) -> list[tuple[Path, str]]:
    """Each `<name>.md` in `where` with its text, less the line break that
    ends it, in name order; a missing folder holds none. Any other file, a
    folder, a text not UTF-8, and an empty one are refused into
    `breaches`."""
    if not where.is_dir():
        return []
    read: list[tuple[Path, str]] = []
    for path in sorted(where.iterdir()):
        if not path.is_file() or path.suffix != ".md" or not NAME.fullmatch(path.stem):
            breaches.append(
                f"{_named(path)}: not a <name>.md, its name lowercase words and hyphens"
            )
            continue
        try:
            text = path.read_text(encoding="utf-8").removesuffix("\n")
        except UnicodeDecodeError:
            breaches.append(f"{_named(path)}: not UTF-8")
            continue
        if not text.strip():
            breaches.append(f"{_named(path)}: empty")
            continue
        read.append((path, text))
    return read


def _entry(kind: str, path: Path, text: str) -> tuple[KindEntry | None, str]:
    """A wiki file as its kind's entry, or why it is refused."""
    matched = HEADER.fullmatch(text)
    if matched is None:
        return None, f"{_named(path)}: no header of its title and its trigger between --- lines"
    fields = dict(line.split(": ", 1) for line in matched["fields"].splitlines())
    if set(fields) != {"title", "trigger"}:
        return (
            None,
            f"{_named(path)}: its header holds {sorted(fields)}, never title and trigger alone",
        )
    trigger = tuple(word.strip() for word in fields["trigger"].split(","))
    try:
        entry = KindEntry(
            kind=kind,
            slug=path.stem,
            title=fields["title"].strip(),
            trigger=tuple(word for word in trigger if word),
            text=matched["text"],
        )
    except ValidationError as refused:
        problems = ", ".join(
            f"{'.'.join(str(part) for part in error['loc'])} {error['msg'].lower()}"
            for error in refused.errors()
        )
        return None, f"{_named(path)}: {problems}"
    return entry, ""


def _findings(path: Path, text: str, reach: LeverReach) -> list[str]:
    """What the lever checks find in a kind's text, a breach each."""
    return [
        f"{_named(path)}: {finding.check.value}: {finding.detail}"
        for finding in checked(text, reach)
    ]


def _named(path: Path) -> str:
    """A file named from its kind's folder on: `<kind>/<folder>/<file>`."""
    return "/".join(path.parts[-3:])
