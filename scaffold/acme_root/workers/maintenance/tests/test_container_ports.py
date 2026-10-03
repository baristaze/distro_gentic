"""The worker's composition settles the holds nobody settled through
billing's money gate, on its ledger, and outside `local` it refuses every
port that would ship a gate open, naming what is missing."""

import re
from pathlib import Path

import pytest
from contracts.ports import open_ports

from acme.infra.impl.local import InfraLocalImpl
from acme.om.billing.gate import MoneyGateInterface
from acme.om.exceptions import UnsafeConfiguration
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.workers.maintenance.container import WorkerContainer
from acme.workers.maintenance.settings import MaintenanceSettings

STAGING = MaintenanceSettings.model_validate(
    {"_env_file": None, "environment": "staging", "worker_id": "maintenance-test"}
)


def test_the_worker_sweeps_the_money_gates_holds_on_its_ledger(tmp_path: Path) -> None:
    storage = StorageMemoryImpl()
    container = WorkerContainer.for_tests(storage, InfraLocalImpl(tmp_path), STAGING)
    assert isinstance(container.managers.budget_gate, MoneyGateInterface)
    holds = container.holds
    assert holds._gate is container.managers.budget_gate  # pyright: ignore[reportPrivateUsage]
    assert holds._ledger is storage.get_money_ledger_storage()  # pyright: ignore[reportPrivateUsage]


def test_the_worker_outside_local_refuses_every_port_that_ships_a_gate_open(
    tmp_path: Path,
) -> None:
    storage = StorageMemoryImpl()
    for named, ports in open_ports(storage):
        with pytest.raises(UnsafeConfiguration, match=re.escape(named)):
            WorkerContainer.for_tests(storage, InfraLocalImpl(tmp_path), STAGING, ports=ports)
