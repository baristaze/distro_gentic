"""The API's composition wires billing's money gate behind every model
call, and outside `local` it refuses every port that would ship a gate
open, naming what is missing."""

import re
from pathlib import Path

import pytest
from contracts.ports import open_ports

from acme.infra.impl.local import InfraLocalImpl
from acme.om.billing.gate import MoneyGateInterface
from acme.om.exceptions import UnsafeConfiguration
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.services.api.container import AppContainer


def test_the_api_wires_the_money_gate(tmp_path: Path) -> None:
    container = AppContainer.for_tests(StorageMemoryImpl(), InfraLocalImpl(tmp_path))
    assert container.settings.environment == "test"
    assert isinstance(container.managers.budget_gate, MoneyGateInterface)


def test_the_api_outside_local_refuses_every_port_that_ships_a_gate_open(tmp_path: Path) -> None:
    storage = StorageMemoryImpl()
    for named, ports in open_ports(storage):
        with pytest.raises(UnsafeConfiguration, match=re.escape(named)):
            AppContainer.for_tests(storage, InfraLocalImpl(tmp_path), ports=ports)
