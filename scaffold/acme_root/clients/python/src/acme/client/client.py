"""The one client of the Acme API: the transport, and each namespace's calls
composed onto it. Every operation is a method that returns a typed view; the
methods of one namespace live in its module under `calls/`, so a change to
one namespace's calls touches that module alone."""

from acme.client.calls.agent_automations import AgentAutomationsCalls
from acme.client.calls.agent_knowledge import AgentKnowledgeCalls
from acme.client.calls.agent_playbooks import AgentPlaybooksCalls
from acme.client.calls.agent_projects import AgentProjectsCalls
from acme.client.calls.agent_sessions import AgentSessionsCalls
from acme.client.calls.change_events import ChangeEventsCalls
from acme.client.calls.connectors import ConnectorsCalls
from acme.client.calls.exec_relay import ExecRelayCalls
from acme.client.calls.hosts import HostsCalls
from acme.client.calls.leases import LeasesCalls
from acme.client.calls.levers import LeversCalls
from acme.client.calls.media import MediaCalls
from acme.client.calls.tenancy import TenancyCalls
from acme.client.calls.tools import ToolsCalls
from acme.client.calls.work import WorkCalls


class ApiClient(
    ChangeEventsCalls,
    LeasesCalls,
    MediaCalls,
    TenancyCalls,
    WorkCalls,
    AgentSessionsCalls,
    # The platform's namespaces.
    AgentAutomationsCalls,
    AgentKnowledgeCalls,
    AgentPlaybooksCalls,
    AgentProjectsCalls,
    ConnectorsCalls,
    ExecRelayCalls,
    HostsCalls,
    LeversCalls,
    ToolsCalls,
):
    """Async. `token` is the bearer every request carries; an operation that
    needs another credential (the sign-in flow) takes it as an argument."""
