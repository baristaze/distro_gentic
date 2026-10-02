"""The runner's composition ends every success through the evidence's
gate, over the work product the product wires, and boots outside `local`
with it."""

from pathlib import Path

from runner_support import ABSENT

from acme.infra.impl.local import InfraLocalImpl
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import scripted_model_providers
from acme.om.agents.impl.manager import AgentsManagerImpl
from acme.om.evidence import WorkProductInterface
from acme.om.evidence.impl.gate import ResultGateEvidenceImpl
from acme.om.evidence.impl.ports import WorkProductAbsentImpl, WorkProductMemoryImpl
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.workers.session_runner.container import RunnerContainer
from acme.workers.session_runner.settings import SessionRunnerSettings


def runner(tmp_path: Path, work_product: WorkProductInterface | None = None) -> RunnerContainer:
    settings = SessionRunnerSettings.model_validate(
        {"_env_file": None, "environment": "staging", "runner_id": "runner-test"}
    )
    return RunnerContainer.over(
        settings,
        StorageMemoryImpl(),
        InfraLocalImpl(tmp_path),
        IntegrationsOverImpl(IdentityProviderAbsentImpl(), scripted_model_providers()),
        agent_kinds=ABSENT,
        work_product=work_product,
    )


def test_the_runners_container_builds_the_evidence_gate(tmp_path: Path) -> None:
    work = WorkProductMemoryImpl()
    for container, reads in (
        (runner(tmp_path, work_product=work), WorkProductMemoryImpl),
        (runner(tmp_path), WorkProductAbsentImpl),
    ):
        agents = container.managers.agents
        assert isinstance(agents, AgentsManagerImpl)
        gate = agents._gate  # pyright: ignore[reportPrivateUsage]
        assert isinstance(gate, ResultGateEvidenceImpl)
        assert isinstance(gate._work_product, reads)  # pyright: ignore[reportPrivateUsage]
