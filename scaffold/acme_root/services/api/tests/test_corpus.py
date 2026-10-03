"""The platform's agents ship by default: a deployed process reads their
corpus from the folder it names, and the image carries that folder's
knowledge map and every document the map lists for tenant users."""

import re
from pathlib import Path

import pytest

from acme.om.exceptions import UnsafeConfiguration
from acme.om.platform_agents import rules
from acme.om.platform_agents.catalog import KNOWLEDGE_MAP
from acme.om.platform_agents.settings import PlatformAgentsSettings, shipped_agents


def repository_root() -> Path:
    """The checkout this test runs in: the nearest folder above it with an
    `.env.example`, so a copy that is not yet a repository reads its own."""
    here = Path(__file__).resolve().parent
    return next(p for p in (here, *here.parents) if (p / ".env.example").is_file())


def copied(dockerfile: str) -> set[str]:
    """The repository paths a Dockerfile's `COPY` lines take from the build
    context: every source but the last word, and none from another stage."""
    sources: set[str] = set()
    for line in dockerfile.splitlines():
        words = line.split()
        if not words or words[0] != "COPY" or any(w.startswith("--from") for w in words):
            continue
        sources.update(w.rstrip("/") for w in words[1:-1] if not w.startswith("--"))
    return sources


def settings(corpus_root: Path | None) -> PlatformAgentsSettings:
    return PlatformAgentsSettings.model_validate({"_env_file": None, "corpus_root": corpus_root})


def test_the_api_image_carries_the_map_and_every_document_it_lists_for_tenants() -> None:
    root = repository_root()
    sources = copied((root / "deployment/docker/api.Dockerfile").read_text())
    listed = [
        entry.path for entry in rules.listed((root / KNOWLEDGE_MAP).read_text(), rules.TENANT_USERS)
    ]

    missing = [
        path
        for path in (KNOWLEDGE_MAP, *listed)
        if not any(path == source or path.startswith(f"{source}/") for source in sources)
    ]

    assert listed and not missing, f"the API image copies none of: {missing}"


def test_outside_local_a_process_that_names_no_corpus_is_refused() -> None:
    with pytest.raises(UnsafeConfiguration, match="no corpus root"):
        shipped_agents(settings(None), "prod")

    assert shipped_agents(settings(None), "local") is None


def test_a_named_corpus_ships_every_document_listed_for_tenants() -> None:
    root = repository_root()

    shipped = shipped_agents(settings(root), "prod")

    assert shipped is not None
    paths = [document.path for document in shipped.corpus.documents]
    assert paths == [
        entry.path for entry in rules.listed((root / KNOWLEDGE_MAP).read_text(), rules.TENANT_USERS)
    ]
    assert all(re.search(r"\S", document.text) for document in shipped.corpus.documents)
