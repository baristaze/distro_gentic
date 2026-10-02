---
name: ops-host-idle
description: "Say why one workspace host of one tenant takes no work, in one environment: read its standing through the operator plane with a read-only operator token (its state, what it advertised, the version of work it reads against the floor, when it last called, and what is ready on its pool's lane and its own), match it against one table of causes, and report the cause and the next step. Takes the org id and the host id. Never writes, never reaches into the tenant's wall, never another tenant's rows."
allowed-tools: Read, Bash(aws:*), Bash(curl:*), Bash(jq:*), Bash(uv run acme-ops size:*)
---

# ops-host-idle

The supporter's skill for one host that takes no work. A host sits
inside its tenant's wall and pulls: it claims from its pool's lane and
its own, as its credential names them, and it is handed only what it
advertised it can run. The operator plane reads what the platform knows
of it, and what waits on its lanes, as one answer; this skill turns
that answer into a cause. What the host decides on its own disk, its
owner's ceilings, stays inside the wall.

Read `../_shared/ops-preamble.md`, a path from this skill's folder,
before the first step: the profiles, the account check, and the env
file are there.

## Input

`--env local|staging|production --org <org_id> --host <host_id>`

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

1. In the cloud, check the profile as Role and credential states,
   before any other command; locally there is none to check. Then run
   `uv run acme-ops size --env <env>`, which refuses an env file that
   holds the provisioner's token. When it refuses, stop, and give the
   person the line it printed. Any other answer is not that refusal, the
   platform's size or an error of its own, and the run goes on.
2. Read who the operator plane admitted, and go on only on
   `operator_role: read`:

   ```bash
   set -a; . ~/.config/acme/ops/<env>.env; set +a
   curl -s -H "Authorization: Bearer $ACME_OPERATOR_TOKEN" "$ACME_API_URL/v1/admin/me" \
     | jq '{operator_role, email_domain: (.email // "" | split("@")[1]), error: .error.code}'
   ```

3. Read the host's standing, once. The `jq` keeps what the host probed
   and what waits for it, and never the name its owner gave it:

   ```bash
   set -a; . ~/.config/acme/ops/<env>.env; set +a
   curl -s -H "Authorization: Bearer $ACME_OPERATOR_TOKEN" "$ACME_API_URL/v1/admin/orgs/<org_id>/hosts/<host_id>/standing" \
     | jq '{state, revoked, pool_id, isolation_modes: .advertisement.isolation_modes, capabilities: .advertisement.capabilities, exec_version, exec_floor, last_seen_at, lanes, error: .error.code}'
   ```

   `not_found` means the tenant holds no such host: the run ends there.
   Any other code, or an answer that is empty or not JSON, ends the run
   the same way, naming it. The read is not made a second time.
4. Find the cause: the first row whose condition holds, top to bottom.

   | Condition | Cause | Next |
   |---|---|---|
   | `revoked` is true | The host was revoked: by its owner, or because two machines held its identity | its owner enrolls it again with a new token |
   | `state` is `below_floor` | It reads a version of `exec` work below the floor, so no work is handed to it | its owner upgrades the host |
   | `state` is `offline` | It has not called since the online window: its process, its machine, or its network inside the wall | its owner; `last_seen_at` says since when |
   | `lanes` is empty | Nothing waits for it: no session runs on its pool now | none: idle is not stuck |
   | `lanes` holds ready items | Work waits and it does not take it: it refuses each item past its owner's ceilings, or at an isolation it did not probe, before anything runs | its owner reads the host's own log, inside the wall |

5. Write the report.

## What it never does

- No write: only `GET` routes of the operator plane, only a `read`
  token.
- No call into the tenant's wall: the platform never calls a host, and
  neither does this skill. The host's own log is its owner's to read.
- No text the tenant wrote: the host's name is left out of every read.
- No data outside `--org`, no second org, no list of hosts.
- No secret value read or printed: the env file is sourced and never
  read.

## Output

```markdown
# Host idle: <env>, org <org_id>, host <host_id>

**Credential.** <profile and Arn, or local>; operator <email domain only>, READ
**Host.** <state>, revoked <yes|no>, last called <last_seen_at>, reads exec <exec_version> (floor <exec_floor>)
**Advertised.** isolation <modes>, capabilities <capabilities>
**Waiting.** <lane: n kind, ...> or nothing

## Cause

<the table's row, with the fields that decided it>

## Next

<the next step the row names, or "none">
```
