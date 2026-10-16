"""Every table belongs to exactly one database role; this map is the single
source of truth for the schema, the pool, and the migration chain."""

from enum import StrEnum


class DatabaseRole(StrEnum):
    CORE = "core"
    ACTIVITY = "activity"
    QUEUE = "queue"
    ADMIN = "admin"


TABLE_ROLES: dict[str, DatabaseRole] = {
    "api_keys": DatabaseRole.CORE,
    "auth_sessions": DatabaseRole.CORE,
    "change_event_cursors": DatabaseRole.ACTIVITY,
    "change_events": DatabaseRole.ACTIVITY,
    "files": DatabaseRole.CORE,
    "idempotency_records": DatabaseRole.CORE,
    "identities": DatabaseRole.CORE,
    "invitations": DatabaseRole.CORE,
    "leasable_resources": DatabaseRole.CORE,
    "lease_requests": DatabaseRole.CORE,
    "leases": DatabaseRole.CORE,
    "memberships": DatabaseRole.CORE,
    "orchestrations": DatabaseRole.CORE,
    "orgs": DatabaseRole.CORE,
    "outbox_rows": DatabaseRole.CORE,
    "sign_in_delays": DatabaseRole.CORE,
    "socket_tickets": DatabaseRole.CORE,
    "system_sizes": DatabaseRole.ADMIN,
    "tenant_caps": DatabaseRole.QUEUE,
    "users": DatabaseRole.CORE,
    "work_items": DatabaseRole.QUEUE,
    # A copy adds its entries below this line.
    "agent_session_authorities": DatabaseRole.CORE,
    "agent_session_keys": DatabaseRole.CORE,
    "agent_session_privacy": DatabaseRole.CORE,
    "agent_sessions": DatabaseRole.CORE,
    "agent_step_cursors": DatabaseRole.ACTIVITY,
    "agent_steps": DatabaseRole.ACTIVITY,
    "agent_trees": DatabaseRole.CORE,
    "fill_sets": DatabaseRole.CORE,
    "spend_budget_holds": DatabaseRole.ACTIVITY,
    "spend_budget_settlements": DatabaseRole.ACTIVITY,
    "spend_budget_tallies": DatabaseRole.ACTIVITY,
    "spend_budgets": DatabaseRole.CORE,
    "tool_outputs": DatabaseRole.ACTIVITY,
    "tool_policies": DatabaseRole.CORE,
    "usage_records": DatabaseRole.ACTIVITY,
    "retention_policies": DatabaseRole.CORE,
    "agent_session_retention": DatabaseRole.CORE,
    "validation_policies": DatabaseRole.CORE,
    "execution_records": DatabaseRole.ACTIVITY,
    "validations": DatabaseRole.ACTIVITY,
    "inferences": DatabaseRole.ACTIVITY,
    "fair_shares": DatabaseRole.CORE,
    "secret_declarations": DatabaseRole.CORE,
    "provider_keys": DatabaseRole.CORE,
    "content_grants": DatabaseRole.CORE,
    "host_pools": DatabaseRole.CORE,
    "host_enrollment_tokens": DatabaseRole.CORE,
    "hosts": DatabaseRole.CORE,
    "host_credentials": DatabaseRole.CORE,
    "agent_session_placements": DatabaseRole.CORE,
    "pool_vms": DatabaseRole.CORE,
    "pool_erasures": DatabaseRole.CORE,
    "installations": DatabaseRole.CORE,
    "identity_links": DatabaseRole.CORE,
    "work_bindings": DatabaseRole.CORE,
    "platform_acts": DatabaseRole.CORE,
    "agent_automations": DatabaseRole.CORE,
    "agent_automation_runs": DatabaseRole.CORE,
    "agent_automation_principals": DatabaseRole.CORE,
    "park_alerts": DatabaseRole.CORE,
    "agent_playbooks": DatabaseRole.CORE,
    "agent_playbook_invocations": DatabaseRole.CORE,
    "agent_playbook_pins": DatabaseRole.CORE,
    "agent_knowledge_entries": DatabaseRole.CORE,
    "agent_knowledge_recalls": DatabaseRole.CORE,
    "connectors": DatabaseRole.CORE,
    "agent_session_connectors": DatabaseRole.CORE,
    "spend_accounts": DatabaseRole.CORE,
    "spend_ledger_entries": DatabaseRole.ACTIVITY,
    "spend_ledger_counts": DatabaseRole.ACTIVITY,
    "validation_sessions": DatabaseRole.CORE,
    "agent_projects": DatabaseRole.CORE,
    "agent_session_projects": DatabaseRole.CORE,
    "exec_items": DatabaseRole.CORE,
    "exec_controls": DatabaseRole.CORE,
    "agent_workspace_bindings": DatabaseRole.CORE,
    "agent_session_workspaces": DatabaseRole.CORE,
    "egress_allowlists": DatabaseRole.CORE,
    "agent_workspace_snapshots": DatabaseRole.CORE,
    "repository_credentials": DatabaseRole.CORE,
    "matrix_versions": DatabaseRole.CORE,
    "benchmark_results": DatabaseRole.CORE,
    "model_retirements": DatabaseRole.CORE,
    "matrix_pins": DatabaseRole.CORE,
    "fill_overrides": DatabaseRole.CORE,
    "benchmarks": DatabaseRole.CORE,
}

DROPPED_TABLE_ROLES: dict[str, DatabaseRole] = {
    "event_cursors": DatabaseRole.ACTIVITY,
    "events": DatabaseRole.ACTIVITY,
    "platform_sizes": DatabaseRole.ADMIN,
    "resources": DatabaseRole.CORE,
    "sessions": DatabaseRole.CORE,
    # A copy adds its entries below this line.
    "artifacts": DatabaseRole.ACTIVITY,
    "budget_holds": DatabaseRole.ACTIVITY,
    "budget_settlements": DatabaseRole.ACTIVITY,
    "budget_tallies": DatabaseRole.ACTIVITY,
    "budgets": DatabaseRole.CORE,
    "session_authorities": DatabaseRole.CORE,
    "session_keys": DatabaseRole.CORE,
    "session_privacy": DatabaseRole.CORE,
    "step_cursors": DatabaseRole.ACTIVITY,
    "steps": DatabaseRole.ACTIVITY,
    "ledger_entries": DatabaseRole.ACTIVITY,
    "ledger_counts": DatabaseRole.ACTIVITY,
    "station_jobs": DatabaseRole.CORE,
    "station_leases": DatabaseRole.CORE,
    "station_line_entries": DatabaseRole.CORE,
    "daemon_credentials": DatabaseRole.CORE,
    "stations": DatabaseRole.CORE,
    "station_pools": DatabaseRole.CORE,
    "labs": DatabaseRole.CORE,
    "billing_accounts": DatabaseRole.CORE,
    "account_links": DatabaseRole.CORE,
    "automations": DatabaseRole.CORE,
    "automation_runs": DatabaseRole.CORE,
    "automation_principals": DatabaseRole.CORE,
    "knowledge_entries": DatabaseRole.CORE,
    "knowledge_recalls": DatabaseRole.CORE,
    "playbooks": DatabaseRole.CORE,
    "playbook_invocations": DatabaseRole.CORE,
    "playbook_pins": DatabaseRole.CORE,
    "notifications": DatabaseRole.CORE,
    "session_retention": DatabaseRole.CORE,
    "session_placements": DatabaseRole.CORE,
    "session_connectors": DatabaseRole.CORE,
    "session_workspaces": DatabaseRole.CORE,
    "workspace_snapshots": DatabaseRole.CORE,
    "workspace_bindings": DatabaseRole.CORE,
    "pool_machines": DatabaseRole.CORE,
    "projects": DatabaseRole.CORE,
    "session_projects": DatabaseRole.CORE,
    "exec_parts": DatabaseRole.CORE,
}
"""Tables the migration chain made and later dropped or renamed, by the name
they had. No process reaches them, so `role_for` does not know them; only the
chain names them, and its role check reads this map beside the live one."""

APPEND_ONLY_TABLES: frozenset[str] = frozenset(
    {
        "agent_steps",
        "spend_budget_holds",
        "spend_budget_settlements",
        "usage_records",
        "tool_outputs",
        "execution_records",
        "validations",
        "inferences",
        "spend_ledger_entries",
        "agent_session_projects",
        "benchmark_results",
        "benchmarks",
    }
)
"""Tables whose rows are written once: the serving logins hold SELECT and
INSERT on them and never UPDATE or DELETE. The migration that creates one
takes the two back from the role's default privileges, and the login command
takes them back again after each grant it makes (ADR 1002, ADR 1006, ADR
1014)."""

PURGED_TABLES: frozenset[str] = frozenset(
    {
        "agent_sessions",
        "agent_steps",
        "agent_step_cursors",
        "tool_outputs",
        "agent_session_authorities",
        "agent_trees",
        "execution_records",
        "validations",
        "inferences",
        "agent_session_projects",
    }
)
"""The tables the purge login reaches: a session, its history and its
tool_outputs, its authority, its tree, its runs, and its agent project's
row, which go together when the session is purged. It holds SELECT and DELETE on them and nothing
else, granted by the migrations that admit it and again by the login
command, and the tenant fence admits it within the tenant its transaction
names and never under the system scope (ADR 1010)."""


def role_for(table_name: str) -> DatabaseRole:
    try:
        return TABLE_ROLES[table_name]
    except KeyError:
        raise LookupError(
            f"table {table_name!r} has no database role; add it to TABLE_ROLES"
        ) from None
