#!/usr/bin/env bash
# Installs or upgrades the workspace host on Linux, as a systemd service that
# runs as its own system user. Run it as root, from a checkout of this
# repository at the platform's version:
#
#   sudo ACME_ENROLLMENT_TOKEN=hen_... deployment/host/install.sh \
#        --api-url https://api.acme.example [--name <host name>] \
#        [--engine rootless] [--no-start]
#
# It makes the user acme-host, with /var/lib/acme-host as its home; builds a
# release of the host from the lock into /opt/acme-host/releases/, owned by
# root, and points /opt/acme-host/current at it; writes /etc/acme-host/host.env
# (root, 600) once, from the flags and the token in the environment, never on
# a command line; installs the unit; and starts it once the owner's ceilings
# are at /etc/acme-host/ceilings.toml. The host's user owns nothing it runs.
#
# --engine rootless points the host at a rootless Docker engine run as
# acme-host, at /run/user/<uid>/docker.sock, and keeps that user's services
# running while nobody is logged in. Setting the engine up is its own step
# (deployment/host/README.md). A rootful engine is never offered to the host.
#
# On macOS it hands over to install-macos.sh.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$(uname -s)" = "Darwin" ]; then
  exec "${HERE}/install-macos.sh" "$@"
fi

SOURCE="$(cd "${HERE}/../.." && pwd)"
API_URL=""
NAME="$(hostname -s 2>/dev/null || hostname)"
ENGINE=""
START=1
while [ $# -gt 0 ]; do
  case "$1" in
    --api-url) API_URL="${2:-}"; shift 2 ;;
    --name) NAME="${2:-}"; shift 2 ;;
    --engine) ENGINE="${2:-}"; shift 2 ;;
    --no-start) START=0; shift ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

USER_NAME=acme-host
PREFIX=/opt/acme-host
CONFIG=/etc/acme-host
STATE=/var/lib/acme-host
UNIT=/etc/systemd/system/acme-host.service
DROPIN=/etc/systemd/system/acme-host.service.d

if [ "$(id -u)" -ne 0 ]; then
  echo "run it as root: it makes a system user and a service" >&2
  exit 1
fi
if ! command -v systemctl >/dev/null; then
  echo "systemd is required: no systemctl here" >&2
  exit 1
fi
if ! command -v uv >/dev/null; then
  echo "uv is required to build the host's release: https://docs.astral.sh/uv/" >&2
  exit 1
fi
if [ ! -f "${SOURCE}/uv.lock" ] || [ ! -f "${SOURCE}/apps/host/pyproject.toml" ]; then
  echo "${SOURCE} is not a checkout of the platform: no uv.lock or apps/host" >&2
  exit 1
fi
case "${ENGINE}" in
  ""|rootless) ;;
  *) echo "--engine takes rootless alone: a rootful engine is root by another name" >&2; exit 2 ;;
esac
# Each value lands in a file systemd parses, so each is held to a plain shape.
TOKEN="${ACME_ENROLLMENT_TOKEN:-}"
if [ -n "${API_URL}" ] && ! [[ "${API_URL}" =~ ^https?://[A-Za-z0-9.:/_-]+$ ]]; then
  echo "--api-url is not an http(s) URL: ${API_URL}" >&2
  exit 2
fi
if ! [[ "${NAME}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$ ]]; then
  echo "--name takes letters, digits, '.', '_', and '-': ${NAME}" >&2
  exit 2
fi
if [ -n "${TOKEN}" ] && ! [[ "${TOKEN}" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "ACME_ENROLLMENT_TOKEN is not a token" >&2
  exit 2
fi

echo "==> the host's user"
if ! id -u "${USER_NAME}" >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "${STATE}" --no-create-home \
    --shell /usr/sbin/nologin "${USER_NAME}"
fi
if [ "$(id -u "${USER_NAME}")" -eq 0 ]; then
  echo "${USER_NAME} is root: the host never runs as root" >&2
  exit 1
fi
install -d -m 0755 -o root -g root "${PREFIX}" "${PREFIX}/releases" "${CONFIG}"
install -d -m 0700 -o "${USER_NAME}" -g "${USER_NAME}" "${STATE}"

echo "==> the release, built from the lock and owned by root"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "${SOURCE}/apps/host/pyproject.toml" | head -1)"
RELEASE="${PREFIX}/releases/${VERSION}-$(date -u +%Y%m%d%H%M%S)"
CACHE="$(mktemp -d)"
trap 'rm -rf "${CACHE}"' EXIT
# The interpreter goes under the prefix too: one under root's home would be
# hidden from the service, whose home is not root's.
(
  cd "${SOURCE}"
  UV_PROJECT_ENVIRONMENT="${RELEASE}" UV_CACHE_DIR="${CACHE}" \
    UV_PYTHON_INSTALL_DIR="${PREFIX}/python" UV_PYTHON_PREFERENCE=only-managed \
    uv sync --frozen --no-dev --no-editable --package acme-host --quiet
)
chown -R root:root "${PREFIX}"
chmod -R go-w "${PREFIX}"
ln -sfn "${RELEASE}" "${PREFIX}/current.next"
mv -T "${PREFIX}/current.next" "${PREFIX}/current"
"${PREFIX}/current/bin/acme-host" --help >/dev/null
echo "    ${RELEASE}"

echo "==> its settings"
if [ ! -f "${CONFIG}/host.env" ]; then
  if [ -z "${API_URL}" ]; then
    echo "--api-url is required on the first install" >&2
    exit 2
  fi
  ENV_NEXT="$(mktemp "${CONFIG}/host.env.XXXXXX")"
  chmod 0600 "${ENV_NEXT}"
  API_URL="${API_URL}" NAME="${NAME}" TOKEN="${TOKEN}" awk '
    /^ACME_API_URL=/ { print "ACME_API_URL=" ENVIRON["API_URL"]; next }
    /^ACME_HOST_NAME=/ { print "ACME_HOST_NAME=" ENVIRON["NAME"]; next }
    /^ACME_ENROLLMENT_TOKEN=/ { print "ACME_ENROLLMENT_TOKEN=" ENVIRON["TOKEN"]; next }
    { print }
  ' "${HERE}/host.env.example" > "${ENV_NEXT}"
  mv "${ENV_NEXT}" "${CONFIG}/host.env"
  echo "    wrote ${CONFIG}/host.env"
else
  echo "    kept ${CONFIG}/host.env"
fi
chown root:root "${CONFIG}/host.env"
chmod 0600 "${CONFIG}/host.env"

echo "==> the unit"
install -m 0644 -o root -g root "${HERE}/acme-host.service" "${UNIT}"
if [ "${ENGINE}" = "rootless" ]; then
  install -d -m 0755 "${DROPIN}"
  cat > "${DROPIN}/engine.conf" <<'CONF'
# The host's container engine: a rootless Docker run as the host's own user.
[Service]
Environment=DOCKER_HOST=unix:///run/user/%U/docker.sock
CONF
  chmod 0644 "${DROPIN}/engine.conf"
  loginctl enable-linger "${USER_NAME}"
fi
systemctl daemon-reload
systemctl enable acme-host.service >/dev/null

if [ "${START}" = 0 ]; then
  echo "==> installed, not started (--no-start)"
  exit 0
fi
if [ ! -f "${CONFIG}/ceilings.toml" ]; then
  echo "==> installed, not started: write the owner's ceilings to ${CONFIG}/ceilings.toml"
  echo "    (deployment/host/README.md), then: systemctl start acme-host"
  exit 0
fi
chown root:root "${CONFIG}/ceilings.toml"
chmod 0644 "${CONFIG}/ceilings.toml"
systemctl restart acme-host.service
echo "==> started: systemctl status acme-host; journalctl -u acme-host"
