#!/usr/bin/env bash
# Installs the workspace host on a Linux machine with systemd, a container
# here, starts it under its unit against a stub of the platform, and holds
# what the installer and the unit promise: the token reaches no process's
# arguments or environment; a hardened umask leaves the release readable; the
# host started while the platform is down comes back on its own; it enrolls
# from inside its walls, as its own user with no capability, and advertises
# the rootless engine its user runs; it writes neither its release nor its
# ceilings, never reaches a rootful engine's socket, and refuses to start in
# that socket's group; and its exposure stays at or under the bound. Needs
# Docker; reaches nothing but the package indexes.
#
#   deployment/host/check/check.sh      (make host-check)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
IMAGE=acme-host-check
BOX="acme-host-check-$$"
PORT=8765
# The token the check enrolls with; no process in the box may show it.
TOKEN=hen_check_from_a_file
# The unit's exposure as `systemd-analyze security` scores it, 0 to 10; what
# the host's work needs (the network, a socket, its own state) keeps it above 0.
EXPOSURE_MAX=1.5

fail() { echo "FAIL: $*" >&2; exit 1; }
in_box() { docker exec "${BOX}" "$@"; }
wait_for() {  # wait_for <seconds> <command...>: until the command succeeds
  local seconds="$1"
  shift
  for _ in $(seq "${seconds}"); do
    "$@" && return 0
    sleep 1
  done
  return 1
}

echo "==> a Linux machine with systemd and a checkout of the platform"
docker build -q -f "${ROOT}/deployment/host/check/check.Dockerfile" -t "${IMAGE}" "${ROOT}" >/dev/null
docker run -d --name "${BOX}" --privileged --cgroupns=host \
  -v /sys/fs/cgroup:/sys/fs/cgroup:rw --tmpfs /run --tmpfs /run/lock "${IMAGE}" >/dev/null
trap 'docker rm -f "${BOX}" >/dev/null 2>&1 || true' EXIT
for _ in $(seq 60); do
  case "$(in_box systemctl is-system-running 2>/dev/null || true)" in
    running|degraded) break ;;
  esac
  sleep 1
done

echo "==> install.sh refuses a token in its environment"
if in_box env ACME_ENROLLMENT_TOKEN=hen_refused /src/deployment/host/install.sh \
  --api-url "http://127.0.0.1:${PORT}" 2>/dev/null; then
  fail "install.sh took a token from its environment"
fi
echo "refused: ACME_ENROLLMENT_TOKEN in the environment"

echo "==> install.sh as root, under umask 027, with the token from a file, before the owner wrote ceilings"
printf '%s\n' "${TOKEN}" | docker exec -i "${BOX}" sh -c 'umask 077; cat > /root/enroll.token'
docker exec "${BOX}" sh -c "umask 027; exec /src/deployment/host/install.sh \
  --token-file /root/enroll.token --api-url http://127.0.0.1:${PORT} --name check-host \
  --engine rootless" &
INSTALL=$!
# Every process's arguments and environment, read while the installer runs.
# The pattern's brackets keep the reading itself from matching.
PATTERN="$(echo "${TOKEN}" | sed 's/_/[_]/')"
SAMPLES=0
SEEN=0
while kill -0 "${INSTALL}" 2>/dev/null; do
  if in_box sh -c "ps -eww -o args= | grep -q '${PATTERN}' \
    || cat /proc/[0-9]*/environ 2>/dev/null | tr '\\0' '\\n' | grep -q '${PATTERN}'"; then
    SEEN=$((SEEN + 1))
  fi
  SAMPLES=$((SAMPLES + 1))
  sleep 0.2
done
wait "${INSTALL}" || fail "install.sh failed"
[ "${SEEN}" = 0 ] || fail "the token showed in ${SEEN} of ${SAMPLES} readings of ps -eo args and /proc/*/environ"
echo "the token in no process's arguments or environment: ${SAMPLES} readings during the install"
in_box grep -q "^ACME_ENROLLMENT_TOKEN=${TOKEN}\$" /etc/acme-host/host.env || fail "host.env holds no token"
echo "the token reached host.env"
if in_box systemctl is-active --quiet acme-host; then
  fail "the host started with no ceilings"
fi
in_box systemctl start acme-host 2>/dev/null || true
wait_for 10 in_box systemctl is-failed --quiet acme-host || fail "the unit starts with no ceilings to bind"
in_box systemctl show -p ExecMainStatus acme-host
in_box systemctl reset-failed acme-host
echo "refused: starting the unit with no ceilings"

echo "==> a rootless engine for acme-host, set up with the engine's own tool"
HOST_UID="$(in_box id -u acme-host)"
RUNTIME="/run/user/${HOST_UID}"
wait_for 30 in_box test -d "${RUNTIME}" || fail "no ${RUNTIME}: acme-host's service manager is not running"
as_user() {
  in_box setpriv --reuid=acme-host --regid=acme-host --init-groups \
    env HOME=/var/lib/acme-host XDG_RUNTIME_DIR="${RUNTIME}" "$@"
}
as_user dockerd-rootless-setuptool.sh install --skip-iptables >/dev/null 2>&1 \
  || { as_user dockerd-rootless-setuptool.sh check; fail "the rootless engine did not install"; }
wait_for 60 in_box test -S "${RUNTIME}/docker.sock" || fail "the rootless engine made no socket"
as_user env DOCKER_HOST="unix://${RUNTIME}/docker.sock" docker info --format \
  'rootless engine {{.ServerVersion}}: {{.SecurityOptions}}'

echo "==> the host started while the platform is down comes back on its own"
in_box /opt/acme-host/current/bin/python -c \
  "import os, socket; socket.socket(socket.AF_UNIX).bind('/run/docker.sock'); os.chmod('/run/docker.sock', 0o666)"
in_box sh -c 'printf "%s\n" "projects = \"all\"" "min_isolation = \"container\"" \
  "egress = []" "readable = []" "people_commands = false" "items_at_once = 1" \
  > /etc/acme-host/ceilings.toml'
in_box systemctl start acme-host
down() { [ "$(in_box systemctl show -p ExecMainStatus --value acme-host)" = 4 ]; }
wait_for 30 down || { in_box journalctl -u acme-host -o cat | tail -20; fail "the host did not exit 4 with the platform down"; }
in_box journalctl -u acme-host -o cat | grep -m1 '^not ready'
in_box systemctl show -p ActiveState -p SubState acme-host | paste -sd ' ' -
in_box systemd-run --quiet --unit=stub-platform \
  /opt/acme-host/current/bin/python /src/deployment/host/check/stub_platform.py "${PORT}"
claimed() { in_box journalctl -u stub-platform -o cat | grep -q "POST /v1/hosts/me/claims"; }
wait_for 60 claimed || { in_box journalctl -u acme-host -o cat | tail -20; fail "the host never claimed"; }
in_box journalctl -u stub-platform -o cat | grep -E '^(GET|POST)' | sort | uniq -c
echo "restarts by systemd, none by a person: $(in_box systemctl show -p NRestarts --value acme-host)"

echo "==> the host advertises the rootless engine"
ENROLLED="$(in_box journalctl -u stub-platform -o cat | grep -m1 '^enrolled')"
echo "${ENROLLED}"
grep -q '"isolation_modes": \["container"\]' <<<"${ENROLLED}" || fail "the host advertised no container isolation"

echo "==> what the host runs as"
PID="$(in_box systemctl show -p MainPID --value acme-host)"
[ "${PID}" != 0 ] || fail "the host is not running"
in_box ps -o user=,uid=,args= -p "${PID}"
[ "$(in_box ps -o uid= -p "${PID}" | tr -d ' ')" != 0 ] || fail "the host runs as root"
in_box grep -E '^(CapEff|CapBnd|NoNewPrivs|Seccomp):' "/proc/${PID}/status"
in_box grep -q '^CapEff:[[:space:]]*0000000000000000$' "/proc/${PID}/status" || fail "the host holds a capability"
in_box grep -q '^NoNewPrivs:[[:space:]]*1$' "/proc/${PID}/status" || fail "the host can gain privileges"
in_box stat -c '%U %a %n' /etc/acme-host/host.env /var/lib/acme-host/credential.json \
  "$(in_box readlink -f /opt/acme-host/current)/bin/acme-host"

echo "==> what the host's user reaches from inside the unit"
as_host() {
  in_box nsenter -t "${PID}" -m -- setpriv --reuid=acme-host --regid=acme-host --clear-groups "$@"
}
PY=/opt/acme-host/current/bin/python
as_host "${PY}" -c "open('/var/lib/acme-host/.check', 'a')" || fail "the host cannot write its own state"
echo "allowed: writing /var/lib/acme-host/.check"
for target in /opt/acme-host/current/bin/acme-host /var/lib/acme-host/ceilings.toml; do
  if as_host "${PY}" -c "open('${target}', 'a')" 2>/dev/null; then
    fail "the host can write ${target}"
  fi
  echo "refused: writing ${target}"
done
if as_host "${PY}" -c "import socket; socket.socket(socket.AF_UNIX).connect('/run/docker.sock')" 2>/dev/null; then
  fail "the host reaches a rootful engine's socket"
fi
echo "refused: connecting to /run/docker.sock"

echo "==> the unit's exposure, at most ${EXPOSURE_MAX}"
VERDICT="$(in_box systemd-analyze security --no-pager acme-host.service | tail -1)"
echo "${VERDICT}"
SCORE="$(echo "${VERDICT}" | grep -oE '[0-9]+\.[0-9]+')"
awk -v score="${SCORE}" -v most="${EXPOSURE_MAX}" 'BEGIN { exit !(score <= most) }' \
  || fail "the unit's exposure ${SCORE} is above ${EXPOSURE_MAX}"

echo "==> acme-host put in a rootful engine's socket group: the host refuses to start"
in_box chgrp docker /run/docker.sock
in_box usermod -aG docker acme-host
in_box systemctl restart acme-host 2>/dev/null || true
refused() { in_box journalctl -u acme-host -o cat | grep -q '^refused: acme-host is in the group docker'; }
wait_for 15 refused || { in_box journalctl -u acme-host -o cat | tail -20; fail "the host did not refuse the group"; }
in_box journalctl -u acme-host -o cat | grep -m1 -A1 '^refused: acme-host is in the group docker'
sleep 2
in_box systemctl show -p ActiveState -p SubState -p NRestarts acme-host | paste -sd ' ' -
if in_box systemctl is-active --quiet acme-host; then
  fail "the host runs in a rootful engine's socket group"
fi
echo "ok: the host runs under its unit, as its own user, at exposure ${SCORE}"
