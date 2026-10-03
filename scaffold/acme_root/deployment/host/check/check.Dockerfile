# A Linux machine with systemd as its first process, a checkout of the
# platform at /src, uv, and Docker's packages for a rootless engine: what a
# tenant has before it runs install.sh. Docker's rootful engine is masked, so
# the only engine that runs is the one check.sh sets up as the host's user.
# check.sh runs it; nothing ships it.
FROM ubuntu:24.04
RUN apt-get update \
    && apt-get install -y --no-install-recommends systemd systemd-sysv dbus dbus-user-session \
       ca-certificates curl iproute2 procps uidmap slirp4netns \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" \
       > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce docker-ce-cli docker-ce-rootless-extras containerd.io \
    && systemctl mask docker.service docker.socket containerd.service \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
COPY . /src
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
