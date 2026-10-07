#!/usr/bin/env bash
# Installs or upgrades the workspace host on Linux, as a systemd service that
# runs as its own system user. Run it as root, from a checkout of this
# repository at the platform's version:
#
#   sudo deployment/host/install.sh --token-file <file> \
#        --api-url https://api.acme.example [--name <host name>] \
#        [--engine rootless] [--no-start]
#
# The host is a claimant, so it installs through the claimant installer,
# deployment/claimant/install.sh, given the host's kind, unit, user, and
# prefix: the user acme-host, with /var/lib/acme-host as its home; a release
# of acme-host under /opt/acme-host, owned by root; /etc/acme-host/host.env
# (root, 600), written once from the flags and the token in the file
# --token-file names (- for standard input), which no command line and no
# environment carries; and the unit acme-host.service. The host's own step,
# dropin.sh, binds the owner's ceilings into its home read-only, and the unit
# starts once they are at /etc/acme-host/ceilings.toml. The host's user owns
# nothing it runs.
#
# --engine rootless points the host at a rootless Docker engine run as
# acme-host, at /run/user/<uid>/docker.sock, gives that user the subordinate
# ids the engine maps, and keeps its services running while nobody is logged
# in. Setting the engine up is its own step (deployment/host/README.md). A
# rootful engine is never offered to the host.
#
# On a machine in a cloud, the host refuses open egress while the cloud's
# metadata service answers: a workspace's commands leave as the host's user,
# and that service hands the machine's credentials to whatever asks. The
# installer says when it answers here; deployment/host/README.md says how to
# drop it for the host's user.
#
# On macOS it hands over to install-macos.sh.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$(uname -s)" = "Darwin" ]; then
  exec "${HERE}/install-macos.sh" "$@"
fi

ENGINE=""
PASSED=()
while [ $# -gt 0 ]; do
  case "$1" in
    --engine) ENGINE="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) PASSED+=("$1"); shift ;;
  esac
done
case "${ENGINE}" in
  ""|rootless) ;;
  *) echo "--engine takes rootless alone: a rootful engine is root by another name" >&2; exit 2 ;;
esac

# The host's names come last, so no flag passed through renames the host.
ACME_HOST_ENGINE="${ENGINE}" exec "${HERE}/../claimant/install.sh" \
  ${PASSED[@]+"${PASSED[@]}"} \
  --kind host --unit acme-host --user acme-host --env-prefix ACME --command acme-host \
  --settings "${HERE}/host.env.example" --dropin "${HERE}/dropin.sh" --requires ceilings.toml
