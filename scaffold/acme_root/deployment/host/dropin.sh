#!/usr/bin/env bash
# The host's own step of the claimant installer, run as root once its unit is
# in place (deployment/claimant/install.sh --dropin). It writes the host's
# drop-ins: the owner's ceilings, bound read-only into the host's home, so
# the unit does not start without them; and, when ACME_HOST_ENGINE is
# rootless, the rootless Docker engine the host's user runs, with the
# subordinate ids it maps and its services kept running while nobody is
# logged in. It says when the machine reaches its cloud's metadata service.
set -euo pipefail
umask 022

: "${CLAIMANT_USER:?}" "${CLAIMANT_CONFIG:?}" "${CLAIMANT_STATE:?}" "${CLAIMANT_DROPIN:?}"

cat > "${CLAIMANT_DROPIN}/ceilings.conf" <<CONF
# The owner's ceilings, which the host reads and never writes. With none in
# ${CLAIMANT_CONFIG}, the unit does not start.
[Service]
BindReadOnlyPaths=${CLAIMANT_CONFIG}/ceilings.toml:${CLAIMANT_STATE}/ceilings.toml
CONF
chmod 0644 "${CLAIMANT_DROPIN}/ceilings.conf"

if [ "${ACME_HOST_ENGINE:-}" = "rootless" ]; then
  HOST_UID="$(id -u "${CLAIMANT_USER}")"
  # The subordinate ids a rootless engine maps its containers' users onto:
  # 65536 of each, past every range the machine already gave out.
  for kind in uid gid; do
    touch "/etc/sub${kind}"
    if ! grep -q "^${CLAIMANT_USER}:" "/etc/sub${kind}"; then
      FIRST="$(awk -F: 'BEGIN { n = 100000 } $2 + $3 > n { n = $2 + $3 } END { print n }' "/etc/sub${kind}")"
      usermod "--add-sub${kind}s" "${FIRST}-$((FIRST + 65535))" "${CLAIMANT_USER}"
    fi
  done
  # The uid itself, not a specifier: in a system unit %U is the manager's, 0.
  cat > "${CLAIMANT_DROPIN}/engine.conf" <<CONF
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
  chmod 0644 "${CLAIMANT_DROPIN}/engine.conf"
  loginctl enable-linger "${CLAIMANT_USER}"
fi

if timeout 2 bash -c ': >/dev/tcp/169.254.169.254/80' 2>/dev/null; then
  echo "==> this machine reaches its cloud's metadata service: the host refuses open egress"
  echo "    until it is dropped for ${CLAIMANT_USER} (deployment/host/README.md)"
fi
