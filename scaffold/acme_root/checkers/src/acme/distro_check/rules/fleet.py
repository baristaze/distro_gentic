"""The fleet group: the operator dashboard's labels are bounded."""

from __future__ import annotations

import ast
from collections.abc import Iterator

from acme.agentic_check.model import Violation
from acme.agentic_check.project import Project, is_under, last, string
from acme.distro_check.registry import rule

METRICS = frozenset({"Counter", "Gauge", "Histogram", "Summary", "Info", "Enum"})
"""The `prometheus_client` metric classes, whose labels a dashboard reads."""
UNBOUNDED = frozenset(
    {
        "tenant",
        "org",
        "organization",
        "host",
        "session",
        "user",
        "person",
        "member",
        "principal",
        "request",
        "workspace",
        "station",
        "project",
        "repository",
    }
)
"""What grows with the tenants and their work: a label that names one has no bound."""
IDENTITY = frozenset({"name", "slug", "email", "key", "uuid", "hash", "url", "ref"})
"""What names one of them when it follows: `tenant_slug`, `host_name`. An id is DEL-35's."""


def unbounded(label: str) -> bool:
    """Whether a label names a value with no bound: a word of `UNBOUNDED`, alone or before a word of `IDENTITY`."""
    head, _, rest = label.lower().partition("_")
    return head in UNBOUNDED and (not rest or rest in IDENTITY)


def labels(call: ast.Call) -> ast.expr | None:
    """The label names a metric is built with: `labelnames=`, else its third positional argument."""
    given = next((k.value for k in call.keywords if k.arg == "labelnames"), None)
    if given is None and len(call.args) >= 3:
        given = call.args[2]
    return given


@rule(
    "FLT-12",
    coverage="partial",
    summary="No Prometheus metric is labelled by a tenant, a host, a session, a person, a request, "
    "a workspace, a station, or a project.",
)
def the_dashboards_labels_are_bounded(project: Project) -> Iterator[Violation]:
    """Every `prometheus_client` metric (`Counter`, `Gauge`, `Histogram`,
    `Summary`, `Info`, `Enum`) the source builds with literal label names,
    `labelnames=` or its third positional argument as a list or a tuple
    of strings, names no label for a value that grows with the tenants:
    a tenant or an org, a host, a session, a person (a user, a member, a
    principal), a request, a workspace, a station, or a project or a
    repository, alone or followed by a name, a slug, an email, a key, a
    uuid, a hash, a url, or a ref (`tenant`, `host_name`). A label that
    ends in `_id` is the guideline's DEL-35, which `arch-check` decides.
    Label names built at run time, the dashboard's definition, and a
    signal missing are judged."""
    for file, tree in project.trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            full = project.full_name(file, node.func) or ""
            if not (is_under(full, "prometheus_client") and last(full) in METRICS):
                continue
            given = labels(node)
            if not isinstance(given, ast.List | ast.Tuple):
                continue
            for element in given.elts:
                label = string(element)
                if label is not None and unbounded(label):
                    yield Violation.at(
                        file.rel,
                        element,
                        f"labels a metric by {label!r}, which has no bound; a view of one is an "
                        "operator-plane read, never a label",
                    )
