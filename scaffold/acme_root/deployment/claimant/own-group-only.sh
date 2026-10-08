#!/bin/sh
# How a claimant's unit (claimant.service) starts it: as the claimant's user,
# inside the unit's walls, it runs the claimant only while that user holds no
# group beyond its own and the ones its unit grants, and then becomes the
# claimant. A group someone adds the user to is a door the walls do not see:
# a rootful engine's socket group is root by another name, and the unit hides
# that socket only as the claimant starts, not one the engine makes again
# later. A process's groups are fixed as it starts, so the refusal here holds
# for the claimant's whole life. It exits 6, which the unit does not restart.
# install.sh puts it at /opt/<unit>/own-group-only.sh.
#
# A group the claimant's kind needs (a device's, or that of an account it runs
# work as) is granted in a drop-in of the unit, with SupplementaryGroups=,
# where the walls show it. install.sh reads those grants once the kind's step
# has written them, and passes each here with --granted, as a name or a gid.
# A unit with no grant passes none, and the check is the one above.
#
#   own-group-only.sh [--granted <group>]... <the claimant's command...>
set -eu

GRANTED=" "
while [ $# -gt 0 ]; do
  case "$1" in
    --granted)
      [ $# -ge 2 ] && [ -n "$2" ] || { echo "--granted takes a group's name or gid" >&2; exit 2; }
      # A name that names no group grants nothing.
      case "$2" in
        *[!0-9]*) GRANT="$(getent group "$2" | cut -d: -f3)" ;;
        *) GRANT="$2" ;;
      esac
      GRANTED="${GRANTED}${GRANT:+${GRANT} }"
      shift 2
      ;;
    --) shift; break ;;
    *) break ;;
  esac
done
[ $# -gt 0 ] || { echo "usage: own-group-only.sh [--granted <group>]... <command...>" >&2; exit 2; }

OWN="$(id -g)"
for GID in $(id -G); do
  [ "${GID}" = "${OWN}" ] && continue
  case "${GRANTED}" in *" ${GID} "*) continue ;; esac
  USER_NAME="$(id -un)"
  NAME="$(getent group "${GID}" | cut -d: -f1)"
  echo "refused: ${USER_NAME} is in the group ${NAME:-${GID}}, which is neither its own nor one its unit grants, and such a group can open a rootful engine's socket, root by another name." >&2
  echo "Take it out (gpasswd -d ${USER_NAME} ${NAME:-${GID}}) and start it again. A group a drop-in of its kind grants is allowed once install.sh runs again." >&2
  exit 6
done
exec "$@"
