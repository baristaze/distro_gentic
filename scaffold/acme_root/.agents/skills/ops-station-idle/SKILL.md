---
name: ops-station-idle
description: "Say why one station of one tenant takes no work, in one environment: read its standing through the operator plane with a read-only operator token (its lab's daemon, its live lease, its line, and its readiness), match it against one table of causes, and report the cause and the next step. Takes the org id and the station id. Never writes, never reaches into the lab, never another tenant's rows."
allowed-tools: Read, Bash(aws:*), Bash(curl:*), Bash(jq:*), Bash(uv run acme-ops size:*)
---

# ops-station-idle

The supporter's skill for one station that takes no work. A station is
served by its lab's daemon inside the tenant's wall, holds at most one
live lease, and hands itself to the session first in its line that it
can serve. The operator plane reads those four, the daemon, the lease,
the line, and the station's readiness, as one answer; this skill turns
that answer into a cause. The station's limits and secrets stay on its
host, and so does the daemon's log.

The stations are optional. A platform without them has no station
routes, and the read of step 3 answers `not_found` for every station.

Read `../_shared/ops-preamble.md`, a path from this skill's folder,
before the first step: the profiles, the account check, and the env
file are there.

## Input

`--env local|staging|production --org <org_id> --station <station_id>`

All three are required; ask for any that is missing.

## Role and credential

The supporter: the investigator plus a read of one named tenant
through the operator plane.

`--env local` needs the compose stack up and the env file below. No
cloud credential.

`--env staging` and `--env production` run under the investigate
profile of that environment, `acme-<env>-investigate`, checked with
`sts get-caller-identity` before any other command as the preamble
states. Refuse any profile wider than the investigate role.

The credential for the plane is the env file's operator token, whose
permission is `read`; a `write` token is refused by this skill even
when the file holds one. Never read the env file; a command that needs
a value sources it in the same command, as every block below does.
Never print a token. On a `401`, which a read through its `jq` prints
as the error code `not_authenticated`, the token has expired: stop,
and name the refresh the preamble gives.

## Procedure

1. Run `uv run acme-ops size --env <env>`, which refuses an env file
   that holds the provisioner's token. When it refuses, stop, and give
   the person the line it printed. In the cloud, check the profile as
   Role and credential states.
2. Read who the operator plane admitted, and go on only on
   `operator_role: read`:

   ```bash
   set -a; . ~/.config/acme/ops/<env>.env; set +a
   curl -s -H "Authorization: Bearer $ACME_OPERATOR_TOKEN" "$ACME_API_URL/v1/admin/me" \
     | jq '{operator_role, email_domain: (.email // "" | split("@")[1]), error: .error.code}'
   ```

3. Read the station's standing, once. The `jq` keeps ids, counts,
   times, and states, and never the names the tenant gave its lab, its
   pool, or its station:

   ```bash
   set -a; . ~/.config/acme/ops/<env>.env; set +a
   curl -s -H "Authorization: Bearer $ACME_OPERATOR_TOKEN" "$ACME_API_URL/v1/admin/orgs/<org_id>/stations/<station_id>/standing" \
     | jq '{lab_id, pool_id, daemon_online, daemon_last_seen_at, lease_id, held_until, line_waiting, line_servable, capabilities, error: .error.code}'
   ```

   `not_found` means the tenant holds no such station, or the platform
   runs no stations: the run ends there and the report says which the
   prompt allows. Any other code, or an answer that is empty or not
   JSON, ends the run the same way, naming it. The read is not made a
   second time.
4. Find the cause: the first row whose condition holds, top to bottom.

   | Condition | Cause | Next |
   |---|---|---|
   | `daemon_online` is false | The lab's daemon has not called: its process, its machine, or its credential, inside the wall | the lab's owner; `daemon_last_seen_at` says since when |
   | `lease_id` set, `held_until` after now | A session holds it, under a live lease | none: busy is not idle |
   | `lease_id` set, `held_until` before now | A lease past its expiry and margin, which the sweep frees at its next pass | `ops-investigate` if it lasts past a sweep interval |
   | `line_waiting` is 0 | Nothing waits for it | none: idle is not stuck |
   | `line_servable` is 0 | Sessions wait in its pool's line, and none asks what it serves (`capabilities`) | the tenant's people: the asks or the station |
   | otherwise | It is ready and a servable session waits, and the daemon claims nothing: the daemon refuses past its station's limits, before anything runs | the lab's owner reads the daemon's own log, inside the wall |

5. Write the report.

## What it never does

- No write: only `GET` routes of the operator plane, only a `read`
  token. Freeing a lease is the sweep's, never this skill's.
- No call into the lab: the platform never calls a daemon, and neither
  does this skill. A station's limits and secrets never leave its host.
- No text the tenant wrote: no lab, pool, or station name.
- No data outside `--org`, no second org, no list of stations.
- No secret value read or printed: the env file is sourced and never
  read.

## Output

```markdown
# Station idle: <env>, org <org_id>, station <station_id>

**Credential.** <profile and Arn, or local>; operator <email domain only>, READ
**Daemon.** <online | offline since <daemon_last_seen_at>>, lab <lab_id>
**Lease.** <none | <lease_id> until <held_until>>
**Line.** <line_waiting> waiting in pool <pool_id>, <line_servable> it can serve

## Cause

<the table's row, with the fields that decided it>

## Next

<the next step the row names, or "none">
```
