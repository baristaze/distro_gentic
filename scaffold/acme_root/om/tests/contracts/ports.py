"""The platform's ports a root refuses outside `local`, each set to what
would ship a gate open: a quiet null for the money gate, the result gate,
and each port a namespace declared, and the engine's own gate in place of
agent billing's. Every root's suite builds its root over each, outside `local`,
and expects the boot refused, naming what is missing."""

from acme.om.agent_workspaces.impl.agent_projects import WorkspaceAgentProjectsNullImpl
from acme.om.agents.impl.gate import ResultGateNullImpl
from acme.om.budgets.impl.gate import BudgetGateImpl, BudgetGateNullImpl, BudgetGateOptions
from acme.om.platform_root import PlatformPorts
from acme.om.retention.impl.agent_projects import SessionAgentProjectNullImpl
from acme.om.storage.root import StorageInterface


def open_ports(storage: StorageInterface) -> list[tuple[str, PlatformPorts]]:
    """Each port that ships a gate open, with the name the refusal says."""
    engine_gate = BudgetGateImpl(
        storage.get_budget_storage(), storage.get_ledger_storage(), BudgetGateOptions()
    )
    return [
        ("BudgetGateNullImpl", PlatformPorts(budget_gate=BudgetGateNullImpl())),
        ("BudgetGateImpl is not the money gate", PlatformPorts(budget_gate=engine_gate)),
        ("ResultGateNullImpl", PlatformPorts(result_gate=ResultGateNullImpl())),
        (
            "SessionAgentProjectNullImpl",
            PlatformPorts(agent_session_projects=SessionAgentProjectNullImpl()),
        ),
        (
            "WorkspaceAgentProjectsNullImpl",
            PlatformPorts(workspace_agent_projects=WorkspaceAgentProjectsNullImpl()),
        ),
    ]
