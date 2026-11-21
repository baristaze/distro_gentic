"""Each kind is a folder of its own: its module's typed versions, each
version's prompt in Markdown pinned by its digest, and the texts it ships
for its sessions, its manuals and its wiki. The engine's prompt check and
the platform's check of the manuals and the wiki hold every folder the
platform ships and every folder the product keeps, and each folder the
product keeps is declared, so its texts reach its sessions. A released
prompt changed in place, a text the lever checks find something in, and a
malformed one each fail the check, naming the file. Each released version
keeps the settings it was released with, as its lock keeps its prompt."""

import hashlib
import importlib
import json
import shutil
from pathlib import Path
from types import ModuleType

import pytest

from acme.om import agents
from acme.om.agents.types.kind import AgentKind
from acme.om.exceptions import UnsafeConfiguration
from acme.om.platform_agents import kinds
from acme.om.platform_agents.folders import (
    MANUALS,
    MAX_MANUALS,
    WIKI,
    KindFolder,
    folder_breaches,
    folder_of,
)
from acme.om.platform_agents.kinds.software_engineer import kind as software_engineer
from acme.om.platform_agents.shipped import FOLDERS, SHIPPED
from acme.om.platform_root import ProductKinds
from acme.om.product_kinds import PRODUCT_KINDS

PLATFORM = Path(kinds.__file__).parent
"""Where the platform keeps its kinds, a folder each."""

PRODUCT = Path(agents.__file__).parent / "kinds"
"""Where the product keeps its own kinds, a folder each, beside the
platform's."""

NAMES = frozenset(kind.name for kind in (*SHIPPED, *PRODUCT_KINDS.agent_kinds))
"""Every kind there is, which a kind's texts may name."""

SETTINGS = {
    (
        kinds.SOFTWARE_ENGINEER,
        1,
    ): "4e63776281abae24b5617a85f1d4363af012c93c3e530a3f2aa3b0e136f2ee40",
    (
        kinds.SOFTWARE_ENGINEER,
        2,
    ): "db66afd53abece76a9b6f6c344392418371842aa5eec004a58a96f840ab5dbac",
    (
        kinds.SOFTWARE_ENGINEER,
        3,
    ): "198cf7b9d9b2ec980233c96376e25250b5ceee935e0c6d7129587680be5bdda7",
    (
        kinds.SOFTWARE_ENGINEER,
        4,
    ): "877ca929fd011e40cafa51d884e3b45b557dff907e5d564de8040083a6d69f6b",
    (
        kinds.SOFTWARE_ENGINEER,
        5,
    ): "cd8d1e88a92d9830100731bc358d991c4bda7f9bf961d6a279f062e949218926",
    (
        kinds.SOFTWARE_ENGINEER,
        6,
    ): "6de03aafe76785f70a60662a45a8ef4e17ef91ac93c1d43fe58de356c2569278",
    (
        kinds.SOFTWARE_ENGINEER,
        7,
    ): "31d7b8a0131a0c23b0f7b88f539bec4fa2a87da502178b54cb65a801d02cdb50",
    (
        kinds.SOFTWARE_ENGINEER,
        8,
    ): "32ecd898fb3eb4e3c3cc3307e4c70d5a881cc5b0744d75a5638ed236bd657ade",
    (kinds.ANALYSIS, 1): "8c3d3e8a2366fcc45c72ab4540edfe5c8757fd238fecbd21c3cb78a2733d01f0",
    (kinds.ANALYSIS, 2): "214b4701510954d9ac7649d615131358a70e1e2fa4ecdc7e7f74faadb3cee07c",
    (kinds.ANALYSIS, 3): "4d1dc9bc365a292f77ed3b4e520a5d985b5a970ce564a697b467ef6a825e05b8",
    (kinds.ANALYSIS, 4): "f47404eae06af6c8ea9eae5048b31554068c0cf3c8e81c107e0e510f9af26ca5",
    (kinds.PLANNER, 1): "799ffc01e5c6d4f2774c3bd1ddac713d2083fa2ea89aa78f6bfa623d8a409a16",
    (
        kinds.PLATFORM_ASSISTANT,
        1,
    ): "8f7d402657d7d3822885d9a0aa773a1595bbcf681f39bc35b781e5c82dea75c0",
    (
        kinds.PLATFORM_ASSISTANT,
        2,
    ): "e6d3bb7229ec1cc222d688dc4cbfd2fbdc9748dcbe7e32d92a1e97bf26d5f765",
    (kinds.REVIEWER, 1): "7136765176c7c91b89ca2effc4f5c94fecf54306c2c168ebf856797c0528ad79",
    (kinds.OPS_ANALYST, 1): "bb0c19ce54d8e4968fcd158d39161a0c7c1d53edba3d8ab60300f1688108df1d",
}
"""Each version of each shipped kind, and the digest of its settings: every
field it sets but its prompt, which its folder's lock pins. A released
version's settings never change: a change is a version of its own, and its
digest joins here. A failure prints the digest of a new one."""


def settings_of(kind: AgentKind) -> str:
    """The digest of what a version sets, its prompt aside, a set sorted."""
    named = kind.model_dump(mode="json", exclude={"prompts"}, exclude_defaults=True)
    if "started_by" in named:
        named["started_by"] = sorted(named["started_by"])
    return hashlib.sha256(json.dumps(named, sort_keys=True).encode()).hexdigest()


def folders_in(root: Path) -> list[Path]:
    """The kind folders under `root`, each with its module at its root."""
    if not root.is_dir():
        return []
    return sorted(folder for folder in root.iterdir() if (folder / "kind.py").is_file())


def versions_of(package: str, folder: Path) -> tuple[AgentKind, ...]:
    """The versions a kind folder's module holds, read as a catalog reads
    them."""
    return folder_of(importlib.import_module(f"{package}.{folder.name}.kind")).versions


def a_folder(tmp_path: Path) -> Path:
    """A copy of the software engineer's folder, to break."""
    return Path(shutil.copytree(PLATFORM / kinds.SOFTWARE_ENGINEER, tmp_path / "software_engineer"))


# Check 1: each shipped version renders its folder's prompt, the text its
# lock pins, and keeps the settings it was released with.


def test_each_shipped_version_keeps_the_settings_it_was_released_with() -> None:
    assert {(kind.name, kind.version): settings_of(kind) for kind in SHIPPED} == SETTINGS


def test_each_shipped_version_renders_its_folders_one_prompt() -> None:
    for folder in FOLDERS:
        for version in folder.versions:
            path = PLATFORM / folder.name / "prompts" / f"v{version.version}.md"
            assert version.prompts == (path.read_text(encoding="utf-8").removesuffix("\n"),)


# Check 3: the engine's prompt check and the platform's check of the manuals
# and the wiki hold each folder the platform ships and the product keeps.


def test_every_kind_folder_passes_the_prompt_check_and_the_texts_check() -> None:
    held = {
        folder.name: folder_breaches(folder, versions_of(package, folder), NAMES)
        for root, package in (
            (PLATFORM, kinds.__name__),
            (PRODUCT, f"{agents.__name__}.kinds"),
        )
        for folder in folders_in(root)
    }
    assert held and all(breaches == () for breaches in held.values()), held


def test_the_platform_ships_each_of_its_folders_and_the_product_declares_each_of_its() -> None:
    assert [folder.name for folder in folders_in(PLATFORM)] == sorted(f.name for f in FOLDERS)
    declared = {folder.name for folder in PRODUCT_KINDS.folders}
    assert {folder.name for folder in folders_in(PRODUCT)} <= declared


def test_a_released_prompt_changed_in_place_fails_the_check(tmp_path: Path) -> None:
    folder = a_folder(tmp_path)
    first = folder / "prompts" / "v1.md"
    first.write_text(first.read_text(encoding="utf-8") + "Then stop.\n", encoding="utf-8")

    breaches = folder_breaches(folder, software_engineer.VERSIONS, NAMES)

    assert breaches == (
        "software_engineer/prompts/v1.md: version 1 renders prompts other than its text",
        "software_engineer/prompts/v1.md: changed under released version 1, whose text stays "
        "as lock.json pins it; a changed prompt is a version of its own",
    )


def test_a_kinds_manual_or_entry_the_lever_checks_find_something_in_fails_the_check(
    tmp_path: Path,
) -> None:
    folder = a_folder(tmp_path)
    (folder / MANUALS).mkdir()
    (folder / WIKI).mkdir()
    (folder / MANUALS / "flaky-tests.md").write_text(
        "When a test fails, keep retrying until it passes.\n", encoding="utf-8"
    )
    (folder / WIKI / "deploys.md").write_text(
        "---\ntitle: Deploys\ntrigger: deploy\n---\n\nAsk the `deploy_now` tool to ship it.\n",
        encoding="utf-8",
    )

    breaches = folder_breaches(folder, software_engineer.VERSIONS, NAMES)

    assert [breach.split(": ")[:2] for breach in breaches] == [
        ["software_engineer/manuals/flaky-tests.md", "unbounded_retry"],
        ["software_engineer/wiki/deploys.md", "unknown_name"],
    ]


@pytest.mark.parametrize(
    ("file", "text", "breach"),
    [
        (f"{WIKI}/deploys.md", "Ship on Fridays.\n", "no header of its title and its trigger"),
        (
            f"{WIKI}/deploys.md",
            "---\ntitle: Deploys\nowner: ops\ntrigger: deploy\n---\n\nShip on Fridays.\n",
            "its header holds ['owner', 'title', 'trigger']",
        ),
        (f"{WIKI}/deploys.md", "---\ntitle: Deploys\ntrigger: ,\n---\n\nShip.\n", "trigger"),
        (f"{MANUALS}/Flaky.md", "Rerun once.\n", "not a <name>.md"),
        (f"{MANUALS}/notes.txt", "Rerun once.\n", "not a <name>.md"),
        (f"{MANUALS}/empty.md", "\n", "empty"),
        (f"{MANUALS}/long.md", "Read the ledger. " * MAX_MANUALS, f"past {MAX_MANUALS}"),
    ],
)
def test_a_malformed_text_fails_the_check_and_refuses_the_folder(
    tmp_path: Path, file: str, text: str, breach: str
) -> None:
    folder = a_folder(tmp_path)
    path = folder / file
    path.parent.mkdir()
    path.write_text(text, encoding="utf-8")

    (found,) = folder_breaches(folder, software_engineer.VERSIONS, NAMES)

    assert found.startswith(f"software_engineer/{file}: ") and breach in found, found
    module = ModuleType("software_engineer")
    module.__file__ = str(folder / "kind.py")
    module.VERSIONS = software_engineer.VERSIONS  # pyright: ignore[reportAttributeAccessIssue]
    with pytest.raises(UnsafeConfiguration, match=f"software_engineer/{file}"):
        folder_of(module)


def test_manuals_past_their_bound_together_fail_the_check(tmp_path: Path) -> None:
    folder = a_folder(tmp_path)
    (folder / MANUALS).mkdir()
    for name in ("first", "second"):
        # Two thirds of the bound each, in words that repeat no phrase.
        text = " ".join(f"{name}{n}" for n in range(MAX_MANUALS // 12))
        assert MAX_MANUALS // 2 < len(text) < MAX_MANUALS
        (folder / MANUALS / f"{name}.md").write_text(text + "\n", encoding="utf-8")

    (found,) = folder_breaches(folder, software_engineer.VERSIONS, NAMES)

    assert found.startswith("software_engineer/manuals/: ") and f"past {MAX_MANUALS}" in found


def test_a_folder_reads_its_manuals_in_name_order_and_its_entries_with_their_triggers(
    tmp_path: Path,
) -> None:
    folder = a_folder(tmp_path)
    (folder / MANUALS).mkdir()
    (folder / WIKI).mkdir()
    (folder / MANUALS / "b-second.md").write_text("Then this.\n", encoding="utf-8")
    (folder / MANUALS / "a-first.md").write_text("This first.\n", encoding="utf-8")
    (folder / WIKI / "branches.md").write_text(
        "---\ntitle: The default branch\ntrigger: default, branch\n---\n\nIt is main.\n",
        encoding="utf-8",
    )
    module = ModuleType("software_engineer")
    module.__file__ = str(folder / "kind.py")
    module.VERSIONS = software_engineer.VERSIONS  # pyright: ignore[reportAttributeAccessIssue]

    read = folder_of(module)

    assert read.manual == "This first.\n\nThen this."
    (entry,) = read.wiki
    assert (entry.handle, entry.title, entry.trigger, entry.text) == (
        "software_engineer/branches",
        "The default branch",
        ("default", "branch"),
        "It is main.",
    )


def test_a_kind_a_product_declares_as_two_folders_or_as_a_folder_and_alone_is_refused() -> None:
    (lone,) = [folder for folder in FOLDERS if folder.name == kinds.PLANNER]
    with pytest.raises(ValueError, match="as two folders"):
        ProductKinds(folders=(lone, KindFolder(versions=lone.versions)))
    with pytest.raises(ValueError, match="as a folder and alone"):
        ProductKinds(agents=lone.versions, folders=(lone,))
    assert ProductKinds(folders=(lone,)).agent_kinds == lone.versions
