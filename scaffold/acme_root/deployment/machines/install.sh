#!/bin/sh
# Installs the host program in a machine of the cloud pool, as root, from the
# source tree given: what the pool's image holds, so every machine the pool
# starts from it runs the host. Run it once in a fresh Linux machine whose
# packages hold Docker, then keep the machine's disk as the image: a Lima
# machine stopped and kept (lima_image.py), or an AMI made from an instance.
#
#   sudo sh deployment/machines/install.sh /path/to/the/source
#
# It writes no secret: the host's settings name where its seed and its home
# are, both on /run, and the pool hands each machine its seed as it starts.
set -eu

SOURCE=${1:?the source tree, with its uv.lock}
UV_VERSION=${UV_VERSION:-0.12.17}
HERE=$(cd "$(dirname "$0")" && pwd)
PREFIX=/opt/acme-host
USER_NAME=acme-host

if [ "$(id -u)" != 0 ]; then
  echo "install.sh runs as root" >&2
  exit 2
fi

export DEBIAN_FRONTEND=noninteractive
if ! command -v docker >/dev/null 2>&1; then
  apt-get update -q
  apt-get install -y -q docker.io docker-buildx
fi
command -v curl >/dev/null 2>&1 || apt-get install -y -q curl
command -v git >/dev/null 2>&1 || apt-get install -y -q git

# The host's own user, in Docker's group: its session's commands run as it,
# and the machine is the session's wall.
if ! id "$USER_NAME" >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/acme-host --create-home \
    --shell /usr/sbin/nologin "$USER_NAME"
fi
usermod -a -G docker "$USER_NAME"

# uv builds the release from the lock, into a prefix root owns.
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" \
    | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi
install -d -m 0755 "$PREFIX"
rm -rf "$PREFIX/src"
cp -a "$SOURCE" "$PREFIX/src"
(
  cd "$PREFIX/src"
  UV_PROJECT_ENVIRONMENT="$PREFIX/venv" UV_PYTHON_INSTALL_DIR="$PREFIX/python" \
    UV_PYTHON_PREFERENCE=only-managed uv sync --frozen --no-dev --no-editable \
    --package acme-host
)
rm -rf "$PREFIX/src"
uv cache clean >/dev/null 2>&1 || true
chmod -R go-w "$PREFIX"

# Its workspace, and its settings and ceilings, which name nothing secret.
install -d -m 0700 -o "$USER_NAME" -g "$USER_NAME" /workspace
install -d -m 0755 /etc/acme-host
install -m 0644 "$HERE/host.env" /etc/acme-host/host.env
install -m 0644 "$HERE/ceilings.toml" /etc/acme-host/ceilings.toml

# Its units: the seed read from the cloud's first-boot data, and the host.
install -d -m 0755 /usr/local/libexec
install -m 0755 "$HERE/acme-machine-seed" /usr/local/libexec/acme-machine-seed
install -m 0644 "$HERE/acme-machine-seed.service" /etc/systemd/system/
install -m 0644 "$HERE/acme-host.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable acme-machine-seed.service acme-host.service
echo "the host is installed; keep this machine's disk as the cloud pool's image"
