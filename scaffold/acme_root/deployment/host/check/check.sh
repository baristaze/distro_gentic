#!/usr/bin/env bash
# Installs the workspace host on a Linux machine with systemd, a container
# here, starts it under its unit against a stub of the platform, and holds
# what the unit promises: the host enrolls and claims from inside its walls,
# as its own user with no capability, writes neither its release nor its
# ceilings, never reaches a rootful engine's socket, and its exposure stays at
# or under the bound. Needs Docker; reaches nothing but the package indexes.
#
#   deployment/host/check/check.sh      (make host-check)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
IMAGE=acme-host-check
BOX="acme-host-check-$$"
PORT=8765
# The unit's exposure as `systemd-analyze security` scores it, 0 to 10; what
# the host's work needs (the network, a socket, its own state) keeps it above 0.
EXPOSURE_MAX=1.5

fail() { echo "FAIL: $*" >&2; exit 1; }
in_box() { docker exec "${BOX}" "$@"; }

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

echo "==> install.sh as root, before the owner wrote ceilings"
in_box env ACME_ENROLLMENT_TOKEN=hen_check /src/deployment/host/install.sh \
  --api-url "http://127.0.0.1:${PORT}" --name check-host
if in_box systemctl is-active --quiet acme-host; then
  fail "the host started with no ceilings"
fi
in_box systemctl start acme-host 2>/dev/null || true
for _ in $(seq 10); do
  in_box systemctl is-failed --quiet acme-host && break
  sleep 1
done
in_box systemctl is-failed --quiet acme-host || fail "the unit starts with no ceilings to bind"
in_box systemctl show -p ExecMainStatus acme-host
in_box systemctl reset-failed acme-host
echo "refused: starting the unit with no ceilings"

echo "==> the platform's stub, a rootful engine's socket, and the owner's ceilings"
in_box systemd-run --quiet --unit=stub-platform \
  /opt/acme-host/current/bin/python /src/deployment/host/check/stub_platform.py "${PORT}"
in_box /opt/acme-host/current/bin/python -c \
  "import os, socket; socket.socket(socket.AF_UNIX).bind('/run/docker.sock'); os.chmod('/run/docker.sock', 0o666)"
in_box sh -c 'printf "%s\n" "projects = \"all\"" "min_isolation = \"container\"" \
  "egress = []" "readable = []" "people_commands = false" "items_at_once = 1" \
  > /etc/acme-host/ceilings.toml'
in_box systemctl start acme-host

echo "==> the host enrolls, beats, and claims"
for _ in $(seq 60); do
  if in_box journalctl -u stub-platform -o cat | grep -q "POST /v1/hosts/me/claims"; then
    break
  fi
  sleep 1
done
in_box journalctl -u stub-platform -o cat | grep -E '^(GET|POST|enrolled)' | sort | uniq -c
in_box journalctl -u stub-platform -o cat | grep -q "POST /v1/hosts/me/claims" \
  || { in_box journalctl -u acme-host -o cat | tail -20; fail "the host never claimed"; }

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
echo "ok: the host runs under its unit, as its own user, at exposure ${SCORE}"
