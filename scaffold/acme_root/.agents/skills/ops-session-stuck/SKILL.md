---
name: ops-session-stuck
description: "Say why one agent session of one tenant is not moving, in one environment: read its standing through the operator plane with a read-only operator token (its status and park, when it last changed, its loop's item, lease, lane, and place in line, its tenant's share, and where it runs), match it against one table of causes, and report the cause and the next step. Takes the org id and the session id. Never opens the session's content, never writes, never another tenant's rows."
allowed-tools: Read, Bash(aws:*), Bash(curl:*), Bash(jq:*), Bash(uv run acme-ops size:*)
---

# ops-session-stuck

The supporter's skill for one session that is not moving. A session is
work: its loop is an item on a lane, claimed by a runner under a lease,
held by its tenant's share, and parked when it waits. The operator
plane reads all of that for one named tenant as one answer, the
session's standing, and this skill turns that answer into a cause. It
reads shape and never content.

Read `../_shared/ops-preamble.md`, a path from this skill's folder,
before the first step: the profiles, the account check, and the env
file are there.

## Input

`--env local|staging|production --org <org_id> --session <session_id>`

All three are required; ask for any that is missing. The ids are the
ones the tenant or an investigation gave, never found by listing.

## Role and credential

The supporter: the investigator plus a read of one named tenant
through the operator plane.

`--env local` needs the compose stack up and the env file below. No
cloud credential.

`--env staging` and `--env production` run under the investigate
profile of that environment, `acme-<env>-investigate`, checked with
`sts get-caller-identity` before any other command as the preamble
states. Refuse any profile wider than the investigate role. The
standing is read through the operator plane, so the profile is checked
and nothing else of the cloud is read.

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
2. Read who the operator plane admitted. The `jq` keeps the role and
   the domain of the operator's address, never the address:

   ```bash
   set -a; . ~/.config/acme/ops/<env>.env; set +a
   curl -s -H "Authorization: Bearer $ACME_OPERATOR_TOKEN" "$ACME_API_URL/v1/admin/me" \
     | jq '{operator_role, email_domain: (.email // "" | split("@")[1]), error: .error.code}'
   ```

   The run goes on only on `operator_role: read`. A `write` stops it,
   and so do an `error` and an answer that is empty or not JSON.
3. Read the session's standing, once:

   ```bash
   set -a; . ~/.config/acme/ops/<env>.env; set +a
   curl -s -H "Authorization: Bearer $ACME_OPERATOR_TOKEN" "$ACME_API_URL/v1/admin/orgs/<org_id>/sessions/<session_id>/standing" \
     | jq '{status, park, changed_at, pending_input, plan_tier, own_lane, concurrency, share_set, pool_id, hosts_online, loop, error: .error.code}'
   ```

   The answer is ids, counts, times, and states, never what the session
   says. `error` is null on an answer. `not_found` means the tenant
   holds no such session: the run ends there and the report says so.
   Any other code, or an answer that is empty or not JSON, ends the run
   the same way, naming it. The read is not made a second time.
4. Find the cause: the first row of this table whose condition holds,
   read top to bottom. `now` is this machine's clock when step 3 runs,
   and a time compares against it.

   | Condition | Cause | Next |
   |---|---|---|
   | `status` is `idle` | Not stuck: no loop is open, and the next input wakes it | none |
   | `status` is `running`, `loop.status` is `claimed`, `loop.lease_expires_at` after now | Moving: a runner (`loop.claimed_by`) holds the loop | none, or read again later |
   | `loop.status` is `claimed`, `loop.lease_expires_at` before now | Its runner died holding the loop; the sweep requeues it under a new writer epoch at its next pass | `ops-investigate` if it lasts past a sweep interval |
   | `loop.status` is `failed` | The loop's item failed for good, a dead letter | a person runs `uv run acme-ops work requeue` |
   | `status` is `parked`, `park.retry_at` before now | Its retry time passed and nothing woke it | `ops-investigate`: the sweep's wake |
   | `status` is `parked`, `park.reason` is `provider` | A provider fails for the credential the session calls it with; `park.unlock` names the provider and the error's kind, and `park.retry_at` is when it tries again by itself | `ops-provider-outage` |
   | `status` is `parked`, `park.reason` is `budget` | The gate refused its spend; `park.unlock` names the funds or the limit | the tenant raises its limit or its funds, on its own screens |
   | `status` is `parked`, `park.reason` is `resource`, `pool_id` set, `hosts_online` is 0 | Its pool has no host online, so its workspace waits | `ops-host-idle` for the pool's hosts |
   | `status` is `parked`, `park.reason` is `resource` | A workspace or a scarce resource it waits for, which `park.unlock` names | none: it tries again at `park.retry_at` |
   | `status` is `parked`, `park.reason` is `person`, `pause`, or `handover` | A person holds it: an approval, a question, a pause, or the environment | the tenant's people, on their own screens |
   | `status` is `parked`, `park.reason` is `job` or `children` | Its tool job or its sub-agents have not reported | none, unless `changed_at` is days old |
   | `status` is `pending`, `loop` is null or `loop.status` is `done` | An input waits and no loop item is open for it | `ops-investigate`: the outbox's relay |
   | `status` is `pending`, `loop.status` is `queued`, `loop.running_ahead` at or above `concurrency` | Its tenant's share holds it: that many of its loops run ahead | an operator raises the share (`PUT /v1/admin/orgs/<org_id>/share`, the write token's) |
   | `status` is `pending`, `loop.status` is `queued`, `loop.available_at` after now | It waits for its time: a delay its last claim set | none |
   | `status` is `pending`, `loop.status` is `queued` | It is `loop.ready_ahead` items into its lane `loop.lane`, and no runner took it | `ops-investigate`: the runners serving that lane |

   A row that names another skill names it as the next step; this run
   does not start it.
5. Write the report.

## What it never does

- No content read: the standing carries none, and this skill never
  calls the content route, which takes a grant of its own.
- No write: only `GET` routes of the operator plane, only a `read`
  token. A fix the report names is a person's to make.
- No data outside `--org`: no list of orgs or sessions, no second org.
- No secret value read or printed: the env file is sourced and never
  read, and no bearer is written to the report.
- No second read of the standing, and no loop: one read decides.

## Output

```markdown
# Session stuck: <env>, org <org_id>, session <session_id>

**Credential.** <profile and Arn, or local>; operator <email domain only>, READ
**Standing.** <status>[, parked on <reason> since <changed_at>, unlock <unlock>, retry <retry_at or none>]
**Loop.** <status> on <lane>, attempt <attempts> of <max_attempts>, lease until <lease_expires_at or none>, <ready_ahead> ahead in line, <running_ahead> of its tenant's running ahead
**Share.** <plan_tier>, <concurrency> at once, own lane <yes|no>, <set by an operator | the default>
**Runs in.** <the cloud | pool <pool_id>, <hosts_online> hosts online>

## Cause

<the table's row, in one or two sentences, with the fields that decided it>

## Next

<the next step the row names, or "none">
```
