#!/usr/bin/env bash
# Installs or upgrades the workspace host on macOS, as a launchd agent of the
# person who runs it, never as root:
#
#   deployment/host/install-macos.sh --token-file <file> \
#        --api-url https://api.acme.example [--name <host name>] [--no-start]
#
# It builds a release of the host from the lock into
# ~/.local/share/acme-host/releases/ and points current at it, and writes
# ~/Library/LaunchAgents/com.acme.host.plist (mode 600) with the platform's
# URL, the host's name, the token in the file --token-file names (- for
# standard input), which no command line and no environment carries, and the
# proxy and CA file this shell names.
# The host's home is ~/.config/acme-host, where its owner writes
# ceilings.toml; the agent starts once that file is there. Logs go to
# ~/Library/Logs/acme-host.log. On macOS the host runs as its owner's own
# user: there is no system user to wall it off with, so the ceilings file is
# its owner's word, not a wall (deployment/host/README.md).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$(cd "${HERE}/../.." && pwd)"
API_URL=""
NAME="$(scutil --get LocalHostName 2>/dev/null || hostname -s)"
TOKEN_FILE=""
START=1
while [ $# -gt 0 ]; do
  case "$1" in
    --api-url) API_URL="${2:-}"; shift 2 ;;
    --name) NAME="${2:-}"; shift 2 ;;
    --token-file) TOKEN_FILE="${2:-}"; shift 2 ;;
    --no-start) START=0; shift ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

LABEL=com.acme.host
PREFIX="${HOME}/.local/share/acme-host"
HOST_HOME="${HOME}/.config/acme-host"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG="${HOME}/Library/Logs/acme-host.log"

if [ "$(id -u)" -eq 0 ]; then
  echo "run it as the person the host works for, not root: a root agent is root" >&2
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
if [ -n "${API_URL}" ] && ! [[ "${API_URL}" =~ ^https?://[A-Za-z0-9.:/_-]+$ ]]; then
  echo "--api-url is not an http(s) URL: ${API_URL}" >&2
  exit 2
fi
if ! [[ "${NAME}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$ ]]; then
  echo "--name takes letters, digits, '.', '_', and '-': ${NAME}" >&2
  exit 2
fi
# The token is read by the shell itself and handed to the plist's writer on a
# file descriptor, so no process's arguments or environment ever hold it.
if [ -n "${ACME_ENROLLMENT_TOKEN:-}" ]; then
  echo "the token is read from --token-file, never the environment" >&2
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
if [ -n "${TOKEN}" ] && ! [[ "${TOKEN}" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "the file --token-file names holds no token" >&2
  exit 2
fi
if [ -z "${API_URL}" ] && [ ! -f "${PLIST}" ]; then
  echo "--api-url is required on the first install" >&2
  exit 2
fi

echo "==> the release, built from the lock"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "${SOURCE}/apps/host/pyproject.toml" | head -1)"
RELEASE="${PREFIX}/releases/${VERSION}-$(date -u +%Y%m%d%H%M%S)"
mkdir -p "${PREFIX}/releases" "${HOST_HOME}" "$(dirname "${PLIST}")" "$(dirname "${LOG}")"
chmod 0700 "${PREFIX}" "${HOST_HOME}"
(
  cd "${SOURCE}"
  UV_PROJECT_ENVIRONMENT="${RELEASE}" UV_PYTHON_INSTALL_DIR="${PREFIX}/python" \
    UV_PYTHON_PREFERENCE=only-managed \
    uv sync --frozen --no-dev --no-editable --package acme-host --quiet
)
ln -sfn "${RELEASE}" "${PREFIX}/current"
"${PREFIX}/current/bin/acme-host" --help >/dev/null
echo "    ${RELEASE}"

echo "==> the agent"
# The release's own interpreter writes the plist, so no value is quoted by
# hand. A value the flags leave out keeps what the last install wrote.
umask 077
PLIST="${PLIST}" LABEL="${LABEL}" PROGRAM="${PREFIX}/current/bin/acme-host" \
  HOST_HOME="${HOST_HOME}" LOG="${LOG}" API_URL="${API_URL}" NAME="${NAME}" \
  "${PREFIX}/current/bin/python" - 3<<<"${TOKEN}" <<'PY'
import os
import plistlib
from pathlib import Path

path = Path(os.environ["PLIST"])
before = plistlib.loads(path.read_bytes()).get("EnvironmentVariables", {}) if path.exists() else {}
environment = {
    "ACME_API_URL": os.environ["API_URL"] or before.get("ACME_API_URL", ""),
    "ACME_HOST_NAME": os.environ["NAME"],
    "ACME_HOST_HOME": os.environ["HOST_HOME"],
    # Docker Desktop's command line, wherever it was linked.
    "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
}
# The token, from the installer's shell on descriptor 3, or the last install's.
token = os.fdopen(3).read().strip() or before.get("ACME_ENROLLMENT_TOKEN")
if token:
    environment["ACME_ENROLLMENT_TOKEN"] = token
for name in ("HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE"):
    value = os.environ.get(name) or before.get(name)
    if value:
        environment[name] = value
agent = {
    "Label": os.environ["LABEL"],
    "ProgramArguments": [os.environ["PROGRAM"], "run"],
    "EnvironmentVariables": environment,
    "WorkingDirectory": os.environ["HOST_HOME"],
    "RunAtLoad": True,
    # Restarted after a failure, never after a clean stop; a setting a person
    # must fix restarts no faster than this.
    "KeepAlive": {"SuccessfulExit": False},
    "ThrottleInterval": 30,
    "ProcessType": "Background",
    "StandardOutPath": os.environ["LOG"],
    "StandardErrorPath": os.environ["LOG"],
}
nxt = path.with_suffix(".next")
nxt.write_bytes(plistlib.dumps(agent))
nxt.chmod(0o600)
nxt.replace(path)
PY
plutil -lint "${PLIST}" >/dev/null
echo "    ${PLIST}"

if [ "${START}" = 0 ]; then
  echo "==> installed, not started (--no-start)"
  exit 0
fi
if [ ! -f "${HOST_HOME}/ceilings.toml" ]; then
  echo "==> installed, not started: write the owner's ceilings to ${HOST_HOME}/ceilings.toml"
  echo "    (deployment/host/README.md), then run this again"
  exit 0
fi
DOMAIN="gui/$(id -u)"
launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "${DOMAIN}" "${PLIST}"
echo "==> started: launchctl print ${DOMAIN}/${LABEL}; tail -f ${LOG}"
