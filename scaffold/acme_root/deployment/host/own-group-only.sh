#!/bin/sh
# How acme-host.service starts the host: as the host's user, inside the
# unit's walls, it runs the host only while that user holds no group beyond
# its own, and then becomes the host. A group someone adds the user to is a
# door the walls do not see: a rootful engine's socket group is root by
# another name, and the unit hides that socket only as the host starts, not
# one the engine makes again later. A process's groups are fixed as it
# starts, so the refusal here holds for the host's whole life. It exits 6,
# which the unit does not restart. install.sh puts it at
# /opt/acme-host/own-group-only.sh.
#
#   own-group-only.sh <the host's command...>
set -eu

OWN="$(id -g)"
for GID in $(id -G); do
  if [ "${GID}" != "${OWN}" ]; then
    USER_NAME="$(id -un)"
    NAME="$(getent group "${GID}" | cut -d: -f1)"
    echo "refused: ${USER_NAME} is in the group ${NAME:-${GID}} as well as its own, and a group beyond its own can open a rootful engine's socket, root by another name." >&2
    echo "Take it out (gpasswd -d ${USER_NAME} ${NAME:-${GID}}) and start the host again." >&2
    exit 6
  fi
done
exec "$@"
