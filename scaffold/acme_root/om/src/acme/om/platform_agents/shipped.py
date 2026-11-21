"""The platform's shipped kinds, each read from its folder (`folders`): the
software engineer, analysis, the planner, the platform assistant, the
reviewer, the ops analyst, and the support assistant. Every process builds its catalog from
`SHIPPED`, the platform's before a product's own kinds."""

from acme.om.platform_agents.folders import KindFolder, folder_of
from acme.om.platform_agents.kinds.analysis import kind as analysis
from acme.om.platform_agents.kinds.ops_analyst import kind as ops_analyst
from acme.om.platform_agents.kinds.planner import kind as planner
from acme.om.platform_agents.kinds.platform_assistant import kind as platform_assistant
from acme.om.platform_agents.kinds.reviewer import kind as reviewer
from acme.om.platform_agents.kinds.software_engineer import kind as software_engineer
from acme.om.platform_agents.kinds.support_assistant import kind as support_assistant

FOLDERS: tuple[KindFolder, ...] = tuple(
    folder_of(module)
    for module in (
        software_engineer,
        analysis,
        planner,
        platform_assistant,
        reviewer,
        ops_analyst,
        support_assistant,
    )
)
"""Every kind the platform ships, as its folder holds it."""

SHIPPED = tuple(version for folder in FOLDERS for version in folder.versions)
"""Every kind the platform ships, at every version it still runs."""
