# The session runner: the maintenance worker's shape, with no exposed port.
# It prepares no workspace of its own in a deployed environment (ADR 2026),
# so it carries no container engine. It carries git: the platform reads a
# session's repository and makes its bundles on its own host. The
# healthcheck asks the serving process's /healthz on its metrics port.
FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY om/pyproject.toml om/
COPY infra/pyproject.toml infra/
COPY integrations/pyproject.toml integrations/
COPY workers/maintenance/pyproject.toml workers/maintenance/
COPY workers/session_runner/pyproject.toml workers/session_runner/
# Every workspace member's manifest, so the frozen lock resolves; only the
# members this image runs are copied whole below.
COPY clients/python/pyproject.toml clients/python/
COPY apps/cli/pyproject.toml apps/cli/
RUN uv sync --frozen --no-dev --package acme-session-runner --no-install-workspace
COPY om om
COPY infra infra
COPY integrations integrations
COPY workers/maintenance workers/maintenance
COPY workers/session_runner workers/session_runner
RUN uv sync --frozen --no-dev --package acme-session-runner
# The knowledge map and the documents it lists for tenant users, outside the
# packages above: the runner ships the platform's agents over them, as the
# API does (ACME_CORPUS_ROOT).
COPY llms.txt ./
COPY apps/cli/README.md apps/cli/
COPY docs/portal-routes.md docs/

FROM python:3.14-slim
RUN apt-get update \
  && apt-get install -y --no-install-recommends git \
  && rm -rf /var/lib/apt/lists/* \
  && useradd --create-home --uid 10001 acme
WORKDIR /app
COPY --from=build --chown=acme:acme /app /app
COPY deployment/docker/entrypoint.sh /entrypoint.sh
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER acme
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s \
  CMD python -c "import os, urllib.request, sys; port = os.environ.get('ACME_RUNNER_METRICS_PORT', '9465'); sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/healthz' % port).status == 200 else 1)"
ENTRYPOINT ["/entrypoint.sh"]
CMD ["acme-session-runner", "serve"]
