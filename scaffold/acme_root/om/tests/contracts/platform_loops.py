"""The loops fixture over the platform's managers: the loop of
`contracts.loops.loop_over`, built on the managers the platform's root
builds, with the options a suite sets on them. A loop's result gate is the
engine's null gate unless a suite hands in its own, as the engine's suites
read it."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acme.om.agent_root import AgentRootOptions
from acme.om.agents.gate import ResultGateInterface
from acme.om.agents.impl.gate import ResultGateNullImpl
from acme.om.platform_root import PlatformManagers, PlatformRootOptions, build_platform_managers
from acme.om.agent_root import LOCAL
from acme.om.storage.root import StorageInterface

from contracts.loops import Loop, loop_over


@dataclass(kw_only=True)
class PlatformLoop(Loop):
    """A loop over the platform's managers: `platform` is the loop's managers,
    read as the platform's."""

    platform: PlatformManagers


def platform_loop_over(
    tmp_path: Path,
    *,
    platform: PlatformRootOptions | None = None,
    result_gate: ResultGateInterface | None = None,
    environment: str = LOCAL,
    **loop: Any,
) -> PlatformLoop:
    """`platform` is what the suite sets on the platform's managers, None the
    defaults; `result_gate` None is the engine's null gate, which accepts a
    result and marks it unverified; `environment` is the root's. `loop` is
    what `loop_over` takes."""
    built: list[PlatformManagers] = []

    def build(storage: StorageInterface, *args: Any, **engine: Any) -> PlatformManagers:
        managers = build_platform_managers(
            storage,
            *args,
            platform_root_options=platform,
            **engine,
            agent_root_options=AgentRootOptions(
                result_gate=result_gate or ResultGateNullImpl(), environment=environment
            ),
        )
        built.append(managers)
        return managers

    over = loop_over(tmp_path, build=build, **loop)
    return PlatformLoop(**vars(over), platform=built[0])
