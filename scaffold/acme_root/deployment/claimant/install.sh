#!/usr/bin/env bash
# Installs or upgrades a claimant on Linux, as a systemd service that runs as
# its own system user: the workspace host (deployment/host/install.sh calls
# it with the host's names), or a product's claimant of a kind of its own.
# Run it as root, from a checkout of the repository at the platform's version:
#
#   sudo deployment/claimant/install.sh --kind <kind> --unit <unit> \
#        --user <user> --env-prefix <PREFIX> --settings <example file> \
#        --token-file <file> --api-url https://api.acme.example \
#        [--name <name>] [--command <distribution>] [--dropin <hook>] \
#        [--requires <file>] [--no-start]
#
# It makes the user, with /var/lib/<unit> as its home; builds a release of
# the distribution --command names (default the unit's name, which is also
# its command) from the lock into /opt/<unit>/releases/, owned by root, and
# points /opt/<unit>/current at it; writes /etc/<unit>/<kind>.env (root, 600)
# once, from the example --settings names, its <PREFIX>_API_URL,
# <PREFIX>_<KIND>_NAME, and <PREFIX>_ENROLLMENT_TOKEN lines filled from the
# flags and the token in the file --token-file names (- for standard input),
# which no command line and no environment carries; renders the unit
# (claimant.service); runs the kind's drop-in hook; and starts it, once the
# file --requires names is in /etc/<unit>. The claimant's user owns nothing
# it runs.
#
# The hook (--dropin) is the kind's own step, run as root once the unit is in
# place: it writes what its kind adds to the unit's walls into
# $CLAIMANT_DROPIN (/etc/systemd/system/<unit>.service.d), and does what else
# its kind needs. It is handed CLAIMANT_KIND, CLAIMANT_UNIT, CLAIMANT_USER,
# CLAIMANT_CONFIG, CLAIMANT_STATE, CLAIMANT_RELEASE, and CLAIMANT_DROPIN. A
# hook that fails stops the install before the unit is enabled.
#
# A group the kind needs (one that opens a file of the machine to it, or that
# of an account it runs work as) the hook grants in a drop-in, with
# SupplementaryGroups=, never by adding the user to the group. Once the hook
# has run, the installer reads the groups the unit's drop-ins grant and passes
# exactly those to the unit's check (own-group-only.sh --granted), which
# refuses any other group the user holds. A kind that grants none, as the
# host, gets the check with none.
set -euo pipefail
# Whatever the shell's umask, the release and the unit's files are readable
# by the claimant's user: the modes below are the ones meant.
umask 022

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$(cd "${HERE}/../.." && pwd)"
KIND=""
UNIT_NAME=""
USER_NAME=""
ENV_PREFIX=""
SETTINGS=""
COMMAND=""
DROPIN_HOOK=""
REQUIRES=""
API_URL=""
NAME="$(hostname -s 2>/dev/null || hostname)"
TOKEN_FILE=""
START=1
while [ $# -gt 0 ]; do
  case "$1" in
    --kind) KIND="${2:-}"; shift 2 ;;
    --unit) UNIT_NAME="${2:-}"; shift 2 ;;
    --user) USER_NAME="${2:-}"; shift 2 ;;
    --env-prefix) ENV_PREFIX="${2:-}"; shift 2 ;;
    --settings) SETTINGS="${2:-}"; shift 2 ;;
    --command) COMMAND="${2:-}"; shift 2 ;;
    --dropin) DROPIN_HOOK="${2:-}"; shift 2 ;;
    --requires) REQUIRES="${2:-}"; shift 2 ;;
    --api-url) API_URL="${2:-}"; shift 2 ;;
    --name) NAME="${2:-}"; shift 2 ;;
    --token-file) TOKEN_FILE="${2:-}"; shift 2 ;;
    --no-start) START=0; shift ;;
    -h|--help) sed -n '2,38p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
COMMAND="${COMMAND:-${UNIT_NAME}}"

# Each name lands in a path, a unit, or a variable, so each is held to a
# plain shape before anything is made.
[[ "${KIND}" =~ ^[a-z][a-z0-9_]{0,31}$ ]] \
  || { echo "--kind takes a claimant kind in lower case: '${KIND}'" >&2; exit 2; }
[[ "${UNIT_NAME}" =~ ^[a-z][a-z0-9-]{0,62}$ ]] \
  || { echo "--unit takes lower-case letters, digits, and '-': '${UNIT_NAME}'" >&2; exit 2; }
[[ "${USER_NAME}" =~ ^[a-z_][a-z0-9_-]{0,30}$ ]] \
  || { echo "--user takes a system user's name: '${USER_NAME}'" >&2; exit 2; }
[[ "${ENV_PREFIX}" =~ ^[A-Z][A-Z0-9_]{0,31}$ ]] \
  || { echo "--env-prefix takes an upper-case prefix such as ACME: '${ENV_PREFIX}'" >&2; exit 2; }
[[ "${COMMAND}" =~ ^[a-z][a-z0-9-]{0,62}$ ]] \
  || { echo "--command takes a distribution's name: '${COMMAND}'" >&2; exit 2; }
[ -f "${SETTINGS}" ] || { echo "--settings: no example file at '${SETTINGS}'" >&2; exit 2; }
if [ -n "${DROPIN_HOOK}" ] && [ ! -x "${DROPIN_HOOK}" ]; then
  echo "--dropin: no executable hook at ${DROPIN_HOOK}" >&2
  exit 2
fi
if [ -n "${REQUIRES}" ] && ! [[ "${REQUIRES}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "--requires takes a file's name in /etc/${UNIT_NAME}: '${REQUIRES}'" >&2
  exit 2
fi

KIND_UPPER="$(printf '%s' "${KIND}" | tr '[:lower:]' '[:upper:]')"
API_VARIABLE="${ENV_PREFIX}_API_URL"
NAME_VARIABLE="${ENV_PREFIX}_${KIND_UPPER}_NAME"
HOME_VARIABLE="${ENV_PREFIX}_${KIND_UPPER}_HOME"
TOKEN_VARIABLE="${ENV_PREFIX}_ENROLLMENT_TOKEN"
PREFIX="/opt/${UNIT_NAME}"
CONFIG="/etc/${UNIT_NAME}"
STATE="/var/lib/${UNIT_NAME}"
ENV_FILE="${CONFIG}/${KIND}.env"
UNIT="/etc/systemd/system/${UNIT_NAME}.service"
DROPIN="${UNIT}.d"

if [ "$(id -u)" -ne 0 ]; then
  echo "run it as root: it makes a system user and a service" >&2
  exit 1
fi
if ! command -v systemctl >/dev/null; then
  echo "systemd is required: no systemctl here" >&2
  exit 1
fi
if ! command -v uv >/dev/null; then
  echo "uv is required to build the release: https://docs.astral.sh/uv/" >&2
  exit 1
fi
PYPROJECT="$(find "${SOURCE}" -maxdepth 3 -name pyproject.toml -not -path '*/node_modules/*' \
  -exec grep -lx "name = \"${COMMAND}\"" {} + 2>/dev/null | head -1 || true)"
if [ ! -f "${SOURCE}/uv.lock" ] || [ -z "${PYPROJECT}" ]; then
  echo "${SOURCE} is not a checkout that builds ${COMMAND}: no uv.lock, or no member of that name" >&2
  exit 1
fi
# The token is read by the shell itself, so no process's arguments or
# environment ever hold it: sudo's command line is in every user's `ps`.
if [ -n "${!TOKEN_VARIABLE:-}" ]; then
  echo "the token is read from --token-file, never the environment (${TOKEN_VARIABLE}): a value on sudo's command line is in every user's ps" >&2
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

echo "==> the claimant's user, ${USER_NAME}"
if ! id -u "${USER_NAME}" >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "${STATE}" --no-create-home \
    --shell /usr/sbin/nologin "${USER_NAME}"
fi
if [ "$(id -u "${USER_NAME}")" -eq 0 ]; then
  echo "${USER_NAME} is root: a claimant never runs as root" >&2
  exit 1
fi
install -d -m 0755 -o root -g root "${PREFIX}" "${PREFIX}/releases" "${CONFIG}"
install -d -m 0700 -o "${USER_NAME}" -g "${USER_NAME}" "${STATE}"

echo "==> the release of ${COMMAND}, built from the lock and owned by root"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "${PYPROJECT}" | head -1)"
RELEASE="${PREFIX}/releases/${VERSION}-$(date -u +%Y%m%d%H%M%S)"
CACHE="$(mktemp -d)"
trap 'rm -rf "${CACHE}"' EXIT
# The interpreter goes under the prefix too: one under root's home would be
# hidden from the service, whose home is not root's.
(
  cd "${SOURCE}"
  UV_PROJECT_ENVIRONMENT="${RELEASE}" UV_CACHE_DIR="${CACHE}" \
    UV_PYTHON_INSTALL_DIR="${PREFIX}/python" UV_PYTHON_PREFERENCE=only-managed \
    uv sync --frozen --no-dev --no-editable --package "${COMMAND}" --quiet
)
chown -R root:root "${PREFIX}"
chmod -R go-w "${PREFIX}"
ln -sfn "${RELEASE}" "${PREFIX}/current.next"
mv -T "${PREFIX}/current.next" "${PREFIX}/current"
"${PREFIX}/current/bin/${COMMAND}" --help >/dev/null
echo "    ${RELEASE}"

echo "==> its settings"
if [ ! -f "${ENV_FILE}" ]; then
  if [ -z "${API_URL}" ]; then
    echo "--api-url is required on the first install" >&2
    exit 2
  fi
  ENV_NEXT="$(mktemp "${ENV_FILE}.XXXXXX")"
  chmod 0600 "${ENV_NEXT}"
  # The shell's own read and printf: the token reaches no other process.
  while IFS= read -r line || [ -n "${line}" ]; do
    case "${line}" in
      "${API_VARIABLE}="*) printf '%s=%s\n' "${API_VARIABLE}" "${API_URL}" ;;
      "${NAME_VARIABLE}="*) printf '%s=%s\n' "${NAME_VARIABLE}" "${NAME}" ;;
      "${TOKEN_VARIABLE}="*) printf '%s=%s\n' "${TOKEN_VARIABLE}" "${TOKEN}" ;;
      *) printf '%s\n' "${line}" ;;
    esac
  done < "${SETTINGS}" > "${ENV_NEXT}"
  mv "${ENV_NEXT}" "${ENV_FILE}"
  echo "    wrote ${ENV_FILE}"
else
  echo "    kept ${ENV_FILE}"
fi
chown root:root "${ENV_FILE}"
chmod 0600 "${ENV_FILE}"

echo "==> the unit, ${UNIT_NAME}.service"
render_unit() {  # render_unit <the check's --granted flags, each after a space>
  local next
  next="$(mktemp)"
  sed -e "s|@UNIT@|${UNIT_NAME}|g" -e "s|@USER@|${USER_NAME}|g" -e "s|@KIND@|${KIND}|g" \
    -e "s|@HOME_VARIABLE@|${HOME_VARIABLE}|g" -e "s|@COMMAND@|${COMMAND}|g" \
    -e "s|@GRANTED@|$1|g" "${HERE}/claimant.service" > "${next}"
  install -m 0644 -o root -g root "${next}" "${UNIT}"
  rm -f "${next}"
}
render_unit ""
install -m 0755 -o root -g root "${HERE}/own-group-only.sh" "${PREFIX}/own-group-only.sh"
install -d -m 0755 -o root -g root "${DROPIN}"
if [ -n "${DROPIN_HOOK}" ]; then
  echo "==> the ${KIND} kind's own step: $(basename "${DROPIN_HOOK}")"
  CLAIMANT_KIND="${KIND}" CLAIMANT_UNIT="${UNIT_NAME}" CLAIMANT_USER="${USER_NAME}" \
    CLAIMANT_CONFIG="${CONFIG}" CLAIMANT_STATE="${STATE}" CLAIMANT_RELEASE="${PREFIX}/current" \
    CLAIMANT_DROPIN="${DROPIN}" "${DROPIN_HOOK}" \
    || { echo "the ${KIND} kind's step failed: fix what it says and install again" >&2; exit 2; }
fi
systemctl daemon-reload
# The groups the drop-ins grant, as systemd reads them, are the ones the check
# allows. Each lands in the unit's ExecStart, so each is held to a plain name
# or a gid, which no specifier, variable, or separator can hide in.
read -r -a GRANTS <<<"$(systemctl show -p SupplementaryGroups --value "${UNIT_NAME}.service")"
GRANTED=""
for group in ${GRANTS[@]+"${GRANTS[@]}"}; do
  if ! [[ "${group}" =~ ^([A-Za-z_][A-Za-z0-9_.-]{0,31}|[0-9]{1,10})$ ]]; then
    echo "a drop-in of ${UNIT_NAME} grants the group '${group}', which is no plain name or gid" >&2
    exit 2
  fi
  GRANTED="${GRANTED} --granted ${group}"
done
if [ -n "${GRANTED}" ]; then
  echo "    the check allows the groups its drop-ins grant: ${GRANTS[*]}"
  render_unit "${GRANTED}"
  systemctl daemon-reload
fi
systemctl enable "${UNIT_NAME}.service" >/dev/null

if [ "${START}" = 0 ]; then
  echo "==> installed, not started (--no-start)"
  exit 0
fi
if [ -n "${REQUIRES}" ]; then
  if [ ! -f "${CONFIG}/${REQUIRES}" ]; then
    echo "==> installed, not started: write ${CONFIG}/${REQUIRES}, then: systemctl start ${UNIT_NAME}"
    exit 0
  fi
  chown root:root "${CONFIG}/${REQUIRES}"
  chmod 0644 "${CONFIG}/${REQUIRES}"
fi
systemctl restart "${UNIT_NAME}.service"
echo "==> started: systemctl status ${UNIT_NAME}; journalctl -u ${UNIT_NAME}"
