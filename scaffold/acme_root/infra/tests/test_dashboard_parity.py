"""The two operator dashboards carry the same panels.

The local one is Grafana's, provisioned into the devx profile; the cloud one
is CloudWatch's, declared in Terraform from a JSON template. What an operator
learns on the local stack is what they see in production, and this test is
what holds the two lists of titles equal.

Two panels differ, and each is named here. CloudWatch computes no
percentile from the statistic set a histogram is exported as, so the cloud
widget reads the load balancer's p95 over every route, and its title says so
instead of claiming a per-route line it cannot draw. And its metric math
divides one series by another, never one search's series by another's, so
the cloud's cache hit rate is every matrix version's together.

Both end on the platform's row: the parks, the ready loops, the hosts, the
model cache, and the spend. Every label they draw is bounded, and so is
every label a process exports: a tenant, a host, a session, or any other id
is an operator-plane read, never a label.
"""

import json
import re
from pathlib import Path

from prometheus_client import REGISTRY

import acme.infra.observability  # noqa: F401  (registers every metric a process exports)

ROOT = Path(__file__).resolve().parents[2]
GRAFANA = ROOT / "deployment" / "local" / "grafana" / "dashboards" / "acme-overview.json"
CLOUD = ROOT / "deployment" / "terraform" / "modules" / "dashboard" / "dashboard.json.tftpl"

LOOP = ROOT / "workers" / "maintenance" / "src" / "acme" / "workers" / "maintenance" / "loop.py"

QUEUE_PANELS = {
    "Work queue oldest ready item age": "work_oldest_ready_seconds",
    "Work items failed in the last fifteen minutes": "work_failed_recently",
    "Outbox oldest pending row age": "outbox_oldest_pending_seconds",
    "Outbox rows failed in the last fifteen minutes": "outbox_failed_recently",
}
"""The last row of both dashboards, the Postgres queue's, by title, and the
field of the sweep's line each one draws; its metric is `acme_<field>`."""

FLEET_PANELS = {
    "Parked sessions by reason and age": "acme_sessions_parked",
    "Ready loops by plan tier": "acme_loops_ready",
    "Hosts by state": "acme_hosts",
    "Model cache hit rate by matrix version": "acme_model_tokens_total",
    "Model spend per minute by matrix version, in dollars": "acme_model_spend_micros_total",
}
"""The platform's row, the last of both dashboards, by local title, and the
metric each one draws."""

BOUNDED_LABELS = {
    "route",
    "method",
    "status",
    "subsystem",
    "outcome",
    "reason",
    "age",
    "plan_tier",
    "state",
    "matrix_version",
    "kind",
}
"""Every label a process exports, each with a closed set of values: a route
template, a status, an outcome, a park's reason and age, a plan's tier, a
host's state, a published matrix version, a kind of token. Any other label
is a new review."""

CLOUD_DIMENSIONS = {"environment", "service", "OTelLib"}
"""The dimensions the collector adds to every series in the cloud."""

CLOUD_TITLE_FOR = {
    "HTTP latency p95 by route": "HTTP latency p95, all routes, at the load balancer",
    "Model cache hit rate by matrix version": (
        "Model cache hit rate, every matrix version together"
    ),
}
"""A local panel whose cloud widget carries another title, and the one it carries."""


def _grafana_titles() -> list[str]:
    return [panel["title"] for panel in json.loads(GRAFANA.read_text())["panels"]]


def _cloud_titles() -> list[str]:
    # The template is JSON with Terraform interpolations and nothing else;
    # every `${name}` becomes null, and the document parses.
    body = json.loads(re.sub(r"\$\{\w+\}", "null", CLOUD.read_text()))
    return [widget["properties"]["title"] for widget in body["widgets"]]


def test_the_cloud_dashboard_carries_every_local_panel_by_title() -> None:
    local = _grafana_titles()
    cloud = _cloud_titles()
    rows = len(QUEUE_PANELS) + len(FLEET_PANELS)
    assert len(local) == 5 + rows, (
        "the local dashboard is the five panels an operator asks first, the queue's row, "
        "and the platform's"
    )
    first = [CLOUD_TITLE_FOR.get(title, title) for title in local[:5]]
    assert cloud[:5] == first, "the first cloud widgets are the local panels, in order"
    assert local[5:] == [*QUEUE_PANELS, *FLEET_PANELS], "the local dashboard ends on both rows"
    fleet = [CLOUD_TITLE_FOR.get(title, title) for title in FLEET_PANELS]
    assert cloud[-rows:] == [*QUEUE_PANELS, *fleet], "and so does the cloud's"


def test_the_cloud_dashboard_adds_the_backing_services_and_the_alarmed_reads() -> None:
    extra = _cloud_titles()[5 : -(len(QUEUE_PANELS) + len(FLEET_PANELS))]
    assert extra == [
        "Database CPU and connections",
        "Cache CPU",
        "Queue messages visible and dead",
        "Running tasks",
        "Read latency p95, the reads with an alarm",
        "Queue oldest message age",
        "Sweep pass duration, the longest per minute",
    ]


def test_the_read_latency_widget_draws_the_metric_the_read_alarms_watch() -> None:
    """The alarms module's log filter writes `acme_read_latency_ms`, one
    series per route, and its alarms read the p95 of it; the widget draws the
    same, for the routes the alarms module names."""
    body = json.loads(re.sub(r"\$\{\w+\}", "null", CLOUD.read_text()))
    (widget,) = [
        widget
        for widget in body["widgets"]
        if widget["properties"]["title"] == "Read latency p95, the reads with an alarm"
    ]
    assert widget["properties"]["stat"] == "p95"
    dashboard = (CLOUD.parent / "main.tf").read_text()
    assert '"Acme", "acme_read_latency_ms", "route"' in dashboard
    alarms = (CLOUD.parent.parent / "alarms" / "main.tf").read_text()
    assert 'name       = "acme_read_latency_ms"' in alarms
    assert 'metric_name         = "acme_read_latency_ms"' in alarms
    assert 'extended_statistic  = "p95"' in alarms


def test_the_cloud_dashboard_reads_the_application_metrics_from_the_acme_namespace() -> None:
    text = CLOUD.read_text()
    # The exporter adds OTelLib to every series, and a schema that leaves out
    # a dimension the series has matches nothing.
    # The namespace is in double quotes, which a name with a space needs; the
    # template is JSON, so each quote reads as an escaped one.
    schemas = re.findall(r"SEARCH\('\{[^}]*\}", text)
    assert schemas, "the application widgets search the Acme namespace"
    quoted = "SEARCH('{" + '\\"Acme\\"' + ",OTelLib,"
    assert all(schema.startswith(quoted) for schema in schemas), schemas
    for metric in ("acme_http_requests_total", "acme_outcomes_total"):
        assert f'MetricName=\\"{metric}\\"' in text


def test_the_cloud_latency_widget_reads_the_load_balancer_p95() -> None:
    body = json.loads(re.sub(r"\$\{\w+\}", "null", CLOUD.read_text()))
    (widget,) = [
        widget
        for widget in body["widgets"]
        if widget["properties"]["title"] == CLOUD_TITLE_FOR["HTTP latency p95 by route"]
    ]
    assert widget["properties"]["stat"] == "p95"
    assert widget["properties"]["metrics"][0][:2] == ["AWS/ApplicationELB", "TargetResponseTime"]


def test_the_queue_widgets_draw_what_the_queue_alarms_watch() -> None:
    """Each inbound queue's backlog alarm reads the age of its oldest
    message, and its dead-letter alarm the messages visible on its `-dead`
    twin; the dashboard draws both, for the same list of queues."""
    dashboard = (CLOUD.parent / "main.tf").read_text()
    assert '["AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName", name' in dashboard
    assert '"ApproximateNumberOfMessagesVisible", "QueueName", "${name}-dead"' in dashboard
    alarms = (CLOUD.parent.parent / "alarms" / "main.tf").read_text()
    assert 'metric_name         = "ApproximateAgeOfOldestMessage"' in alarms
    assert 'dimensions          = { QueueName = "${each.key}-dead" }' in alarms
    environment = (CLOUD.parent.parent / "environment" / "main.tf").read_text()
    # Both modules take the queue module's one list, so a queue added there
    # is drawn and alarmed on together.
    assert len(re.findall(r"queue_names\s+= module\.queue\.queue_names", environment)) == 2


def test_the_sweep_widget_draws_the_metric_the_sweep_alarm_watches() -> None:
    """The alarms module's log filter writes `acme_sweep_duration_ms` from
    the line the worker writes per pass, and its alarm reads the longest
    pass; the widget draws the same. The filter reads the worker's log
    group, which the environment hands it."""
    body = json.loads(re.sub(r"\$\{\w+\}", "null", CLOUD.read_text()))
    (widget,) = [
        widget
        for widget in body["widgets"]
        if widget["properties"]["title"] == "Sweep pass duration, the longest per minute"
    ]
    assert widget["properties"]["stat"] == "Maximum"
    assert widget["properties"]["metrics"][0][:2] == ["Acme", "acme_sweep_duration_ms"]
    alarms = (CLOUD.parent.parent / "alarms" / "main.tf").read_text()
    assert 'pattern        = "{ $.sweep.duration_ms = * }"' in alarms
    assert 'name      = "acme_sweep_duration_ms"' in alarms
    assert 'metric_name         = "acme_sweep_duration_ms"' in alarms
    environment = (CLOUD.parent.parent / "environment" / "main.tf").read_text()
    assert "maintenance_log_group_name = module.maintenance.log_group_name" in environment


def test_the_queue_row_draws_what_the_postgres_queue_alarms_watch() -> None:
    """The worker writes each of the four as a field of its sweep line and
    as a gauge of the metric's name. The alarms module's filters turn each
    field into `acme_<field>` in the cloud, from the worker's log group, and
    one alarm reads each; the cloud widget draws the same metric, and the
    Grafana panel the gauge."""
    body = json.loads(re.sub(r"\$\{\w+\}", "null", CLOUD.read_text()))
    widgets = {widget["properties"]["title"]: widget["properties"] for widget in body["widgets"]}
    panels = {panel["title"]: panel for panel in json.loads(GRAFANA.read_text())["panels"]}
    alarms = (CLOUD.parent.parent / "alarms" / "main.tf").read_text()
    loop = LOOP.read_text()
    assert 'pattern        = "{ $.sweep.${each.key} = * }"' in alarms
    assert 'name      = "acme_${each.key}"' in alarms
    for title, field in QUEUE_PANELS.items():
        metric = f"acme_{field}"
        assert widgets[title]["stat"] == "Maximum"
        assert widgets[title]["metrics"][0][:2] == ["Acme", metric]
        assert f"max({metric})" in panels[title]["targets"][0]["expr"]
        assert re.search(rf"^\s+{field}\s+= \"", alarms, re.MULTILINE), field
        assert f'metric_name         = "{metric}"' in alarms
        assert f'"{field}"' in loop, f"the sweep's line carries {field}"


def _grafana_labels(expr: str, legend: str) -> set[str]:
    """The labels a panel splits by: each `by (...)` and each `{{label}}`."""
    split = {
        name.strip() for group in re.findall(r"by \(([^)]*)\)", expr) for name in group.split(",")
    }
    return split | set(re.findall(r"\{\{(\w+)\}\}", legend))


def test_the_platforms_row_draws_each_signal_by_bounded_labels_on_both_dashboards() -> None:
    panels = {panel["title"]: panel for panel in json.loads(GRAFANA.read_text())["panels"]}
    body = json.loads(re.sub(r"\$\{\w+\}", "null", CLOUD.read_text()))
    widgets = {widget["properties"]["title"]: widget["properties"] for widget in body["widgets"]}
    for title, metric in FLEET_PANELS.items():
        (target,) = panels[title]["targets"]
        assert metric in target["expr"], title
        assert _grafana_labels(target["expr"], target["legendFormat"]) <= BOUNDED_LABELS, title
        cloud = json.dumps(widgets[CLOUD_TITLE_FOR.get(title, title)]["metrics"])
        assert f'MetricName=\\"{metric}\\"' in cloud, title
        for schema in re.findall(r"SEARCH\('\{([^}]*)\}", cloud):
            dimensions = {name.strip('\\"') for name in schema.split(",")} - {"Acme"}
            assert dimensions - CLOUD_DIMENSIONS <= BOUNDED_LABELS, (title, dimensions)


def test_every_label_a_process_exports_is_bounded() -> None:
    """A label is a series per value: a tenant, a host, or a session as one
    is a series per customer, and the bill and the dashboard grow with them.
    Every metric the processes register is labelled by bounded values alone,
    and no label names an id."""
    found = {
        label
        for collector in REGISTRY._collector_to_names  # pyright: ignore[reportPrivateUsage]
        for label in getattr(collector, "_labelnames", ())
    }
    assert found, "this test no longer sees the registered metrics"
    assert not {
        label
        for label in found
        if label.endswith("_id") or label in {"tenant", "org", "host", "session"}
    }
    assert found <= BOUNDED_LABELS, sorted(found - BOUNDED_LABELS)
