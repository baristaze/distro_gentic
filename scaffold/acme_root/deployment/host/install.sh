#!/usr/bin/env bash
# Installs or upgrades the workspace host on Linux, as a systemd service that
# runs as its own system user. Run it as root, from a checkout of this
# repository at the platform's version:
#
#   sudo deployment/host/install.sh --token-file <file> \
#        --api-url https://api.acme.example [--name <host name>] \
#        [--engine rootless] [--no-start]
#
# It makes the user acme-host, with /var/lib/acme-host as its home; builds a
# release of the host from the lock into /opt/acme-host/releases/, owned by
# root, and points /opt/acme-host/current at it; writes /etc/acme-host/host.env
# (root, 600) once, from the flags and the token in the file --token-file
# names (- for standard input), which no command line and no environment
# carries; installs the unit; and starts it once the owner's ceilings are at
# /etc/acme-host/ceilings.toml. The host's user owns nothing it runs.
#
# --engine rootless points the host at a rootless Docker engine run as
# acme-host, at /run/user/<uid>/docker.sock, gives that user the subordinate
# ids the engine maps, and keeps its services running while nobody is logged
# in. Setting the engine up is its own step (deployment/host/README.md). A
# rootful engine is never offered to the host.
#
# On macOS it hands over to install-macos.sh.
set -euo pipefail
# Whatever the shell's umask, the release and the unit's files are readable
# by the host's user: the modes below are the ones meant.
umask 022

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$(uname -s)" = "Darwin" ]; then
  exec "${HERE}/install-macos.sh" "$@"
fi

SOURCE="$(cd "${HERE}/../.." && pwd)"
API_URL=""
NAME="$(hostname -s 2>/dev/null || hostname)"
ENGINE=""
TOKEN_FILE=""
START=1
while [ $# -gt 0 ]; do
  case "$1" in
    --api-url) API_URL="${2:-}"; shift 2 ;;
    --name) NAME="${2:-}"; shift 2 ;;
    --engine) ENGINE="${2:-}"; shift 2 ;;
    --token-file) TOKEN_FILE="${2:-}"; shift 2 ;;
    --no-start) START=0; shift ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
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
# The token is read by the shell itself, so no process's arguments or
# environment ever hold it: sudo's command line is in every user's `ps`.
if [ -n "${ACME_ENROLLMENT_TOKEN:-}" ]; then
  echo "the token is read from --token-file, never the environment: a value on sudo's command line is in every user's ps" >&2
  exit 2
fi
TOKEN=""
if [ "${TOKEN_FILE}" = "-" ]; then
  read -r TOKEN || true
elif [ -n "${TOKEN_FILE}" ]; then
  if [ ! -f "${TOKEN_FILE}" ]; then
    echo "--token-file: no file at ${TOKEN_FILE}" >&2
    exit 2
  fi
  read -r TOKEN < "${TOKEN_FILE}" || true
fi
# Each value lands in a file systemd parses, so each is held to a plain shape.
if [ -n "${API_URL}" ] && ! [[ "${API_URL}" =~ ^https?://[A-Za-z0-9.:/_-]+$ ]]; then
  echo "--api-url is not an http(s) URL: ${API_URL}" >&2
  exit 2
fi
if ! [[ "${NAME}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$ ]]; then
  echo "--name takes letters, digits, '.', '_', and '-': ${NAME}" >&2
  exit 2
fi
if [ -n "${TOKEN}" ] && ! [[ "${TOKEN}" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "the file --token-file names holds no token" >&2
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
  # The shell's own read and printf: the token reaches no other process.
  while IFS= read -r line || [ -n "${line}" ]; do
    case "${line}" in
      ACME_API_URL=*) printf 'ACME_API_URL=%s\n' "${API_URL}" ;;
      ACME_HOST_NAME=*) printf 'ACME_HOST_NAME=%s\n' "${NAME}" ;;
      ACME_ENROLLMENT_TOKEN=*) printf 'ACME_ENROLLMENT_TOKEN=%s\n' "${TOKEN}" ;;
      *) printf '%s\n' "${line}" ;;
    esac
  done < "${HERE}/host.env.example" > "${ENV_NEXT}"
  mv "${ENV_NEXT}" "${CONFIG}/host.env"
  echo "    wrote ${CONFIG}/host.env"
else
  echo "    kept ${CONFIG}/host.env"
fi
chown root:root "${CONFIG}/host.env"
chmod 0600 "${CONFIG}/host.env"

echo "==> the unit"
install -m 0644 -o root -g root "${HERE}/acme-host.service" "${UNIT}"
install -m 0755 -o root -g root "${HERE}/own-group-only.sh" "${PREFIX}/own-group-only.sh"
if [ "${ENGINE}" = "rootless" ]; then
  HOST_UID="$(id -u "${USER_NAME}")"
  # The subordinate ids a rootless engine maps its containers' users onto:
  # 65536 of each, past every range the machine already gave out.
  for kind in uid gid; do
    touch "/etc/sub${kind}"
    if ! grep -q "^${USER_NAME}:" "/etc/sub${kind}"; then
      FIRST="$(awk -F: 'BEGIN { n = 100000 } $2 + $3 > n { n = $2 + $3 } END { print n }' "/etc/sub${kind}")"
      usermod "--add-sub${kind}s" "${FIRST}-$((FIRST + 65535))" "${USER_NAME}"
    fi
  done
  install -d -m 0755 "${DROPIN}"
  # The uid itself, not a specifier: in a system unit %U is the manager's, 0.
  cat > "${DROPIN}/engine.conf" <<CONF
# The host's container engine: a rootless Docker run as the host's own user,
# under that user's service manager. Its runtime directory is the one part
# of /run/user the host sees, read-only: the socket is all it uses there.
[Unit]
Wants=user@${HOST_UID}.service
After=user@${HOST_UID}.service

[Service]
Environment=DOCKER_HOST=unix:///run/user/${HOST_UID}/docker.sock
ProtectHome=tmpfs
BindReadOnlyPaths=/run/user/${HOST_UID}
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
