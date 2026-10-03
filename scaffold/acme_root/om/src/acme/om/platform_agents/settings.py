"""Where a process reads the platform assistant's corpus from: the folder
whose knowledge map, `llms.txt`, lists what the tenant's users read. A
process that knows it ships the platform's agents by default; the image
carries the map and the documents it lists, and names the folder."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from acme.om.exceptions import UnsafeConfiguration
from acme.om.platform_agents.catalog import PlatformAgents, read_corpus
from acme.om.root import LOCAL


class PlatformAgentsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ACME_", env_file=".env", extra="ignore")

    # The folder whose llms.txt lists the assistant's corpus; None ships no
    # platform agents, which only a local stack may.
    corpus_root: Path | None = None


def shipped_agents(settings: PlatformAgentsSettings, environment: str) -> PlatformAgents | None:
    """The platform's agents over the corpus the settings name. Outside
    `local`, a process that names no corpus is refused at boot
    (`UnsafeConfiguration`): it would run none of the agents the platform
    ships, and say nothing."""
    root = settings.corpus_root
    if root is None:
        if environment == LOCAL:
            return None
        raise UnsafeConfiguration(
            f"no corpus root: the platform's agents ship with none, and none is "
            f"refused when the environment is {environment}"
        )
    return PlatformAgents(corpus=read_corpus(root))
