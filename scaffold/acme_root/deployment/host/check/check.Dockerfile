# A Linux machine with systemd as its first process, a checkout of the
# platform at /src, and uv: what a tenant has before it runs install.sh.
# check.sh runs it; nothing ships it.
FROM ubuntu:24.04
RUN apt-get update \
    && apt-get install -y --no-install-recommends systemd systemd-sysv dbus ca-certificates procps \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
COPY . /src
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
