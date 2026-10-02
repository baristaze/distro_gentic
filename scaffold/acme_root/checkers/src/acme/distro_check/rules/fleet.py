"""The fleet group: the operator dashboard's labels are bounded."""

from __future__ import annotations

import ast
from collections.abc import Iterator

from acme.agentic_check.model import Violation
from acme.agentic_check.project import Project, SourceFile, is_under, last, string
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


def assigned(tree: ast.Module, name: str) -> ast.expr | None:
    """The value a module assigns `name` at its top level, the last assignment's; else None."""
    found: ast.expr | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            found = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name and node.value is not None:
                found = node.value
    return found


def spelled(
    project: Project, file: SourceFile, tree: ast.Module, given: ast.expr | None
) -> ast.List | ast.Tuple | None:
    """The literal a metric's label names are: `given` itself, or the module constant it names,
    defined in this module or imported from another; else None."""
    if given is None or isinstance(given, ast.List | ast.Tuple):
        return given
    if isinstance(given, ast.Name) and (own := assigned(tree, given.id)) is not None:
        return own if isinstance(own, ast.List | ast.Tuple) else None
    full = project.full_name(file, given)
    module, _, name = (full or "").rpartition(".")
    source = project.by_module.get(module)
    other = project.tree(source) if source is not None else None
    value = assigned(other, name) if other is not None else None
    return value if isinstance(value, ast.List | ast.Tuple) else None


@rule(
    "FLT-12",
    coverage="partial",
    summary="No Prometheus metric is labelled by a tenant, a host, a session, a person, a request, "
    "a workspace, a station, or a project, in a literal or a module constant.",
)
def the_dashboards_labels_are_bounded(project: Project) -> Iterator[Violation]:
    """Every `prometheus_client` metric (`Counter`, `Gauge`, `Histogram`,
    `Summary`, `Info`, `Enum`) whose label names, `labelnames=` or its
    third positional argument, are a list or a tuple of strings, written
    in the call or assigned to a module constant it names (defined in
    its module or imported from another), names no label for a value
    that grows with the tenants:
    a tenant or an org, a host, a session, a person (a user, a member, a
    principal), a request, a workspace, a station, or a project or a
    repository, alone or followed by a name, a slug, an email, a key, a
    uuid, a hash, a url, or a ref (`tenant`, `host_name`). A label that
    ends in `_id` is the guideline's DEL-35, which `arch-check` decides.
    Label names built any other way, the dashboard's definition, and a
    signal missing are judged."""
    for file, tree in project.trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            full = project.full_name(file, node.func) or ""
            if not (is_under(full, "prometheus_client") and last(full) in METRICS):
                continue
            given = labels(node)
            literal = spelled(project, file, tree, given)
            if literal is None:
                continue
            for element in literal.elts:
                label = string(element)
                if label is not None and unbounded(label):
                    # a label a constant holds is reported where the metric names the constant
                    yield Violation.at(
                        file.rel,
                        element if literal is given else given,
                        f"labels a metric by {label!r}, which has no bound; a view of one is an "
                        "operator-plane read, never a label",
                    )
