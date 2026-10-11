---
name: audit-agent-levers
description: "Audit which levers an org's agents stalled after, in one environment: the playbooks its sessions invoked and the knowledge they recalled, ranked by how much more often the sessions that reached them stalled (a call made again and again, a call failing again and again, a request sent again unchanged, a nudge, a guard, a loop a bound ended), read through the operator plane with a read-only operator token by `acme-ops levers`; then a report with verdicts and proposed tickets. Never changes anything."
allowed-tools: Read, Write, Bash(curl:*), Bash(jq:*), Bash(uv run acme-ops size:*), Bash(uv run acme-ops levers:*)
---

# audit-agent-levers

Which of a tenant's levers came before its agents stalled. A lever is a
text the tenant customizes its agents with: a playbook a principal
invokes into a session, or a reviewed knowledge entry a session
recalls (ADR 2054). A lever written for people can make an agent spin:
a phrase said until it looks load-bearing, a must and a must-not on one
subject, a tool no kind holds, a "keep trying until it works". The
checks that run as a person publishes a lever catch some of it; this
audit reads what happened after. The engine records a stall in its
steps' headers, and the operator plane's reading ranks each lever by
how much more often the sessions that reached it stalled than the
sessions that did not, and names the sessions behind the figure. A
lever every session reached ranks nowhere: it has nothing to stand
against.

Read `../_shared/ops-preamble.md`, a path from this skill's folder,
before the first step: the env file and the token's refresh are there.
Its check of a cloud profile before any other command does not apply
to this skill, which runs no `aws` command in any environment: `local`
reads the local API that the env file names, and no cloud is needed.

## Input

`--env local|staging|production --org <org_id> [--days <n>]`

`--env` and `--org` are required; ask for them when missing. `--days`
is how far back the window opens, 7 when it is not given. The reading
reads at most 200 sessions, the newest first, and at most 10,000 steps
of one; it says when the window held more.

## Role and credential

Supporter, the operator plane's read alone: the env file's operator
token, whose permission is `read`. No cloud profile is needed or used.
The reads are `/v1/admin/me` at `ACME_API_URL`, and the levers route,
`/v1/admin/orgs/<org_id>/levers`, which `uv run acme-ops levers` reads
with the same token. A reading holds ids, versions, and counts: each
lever by its kind, id, and version, never its name, which the tenant
chose.

Before step 2 sources the env file, run `uv run acme-ops size --env
<env>`, which refuses a file that holds the provisioner's token: then
stop, and give the person the line it printed. Any other answer, the
size or an error of its own, is not that refusal, and the run goes on.

A `write` operator is refused by this skill even when the file holds
its token (step 2). Never read the env file; a command that needs a
value sources it in the same command, as step 2 does, or leaves it to
`acme-ops`. Never print a token. On a `401`, which a read prints as the
error code `not_authenticated` and `acme-ops` as a refused token, the
token has expired: stop, and name the refresh the preamble gives.

## Procedure

1. Run `uv run acme-ops size --env <env>`, as Role and credential
   states.
2. Read who the operator plane admitted:

   ```bash
   set -a; . ~/.config/acme/ops/<env>.env; set +a
   curl -s -H "Authorization: Bearer $ACME_OPERATOR_TOKEN" "$ACME_API_URL/v1/admin/me" \
     | jq '{operator_role, error: .error.code}'
   ```

   The run goes on only on `operator_role: read`. A `write` stops it,
   and so do an `error` and an answer that is empty or that `jq`
   cannot parse: the report then says the operator plane was not read,
   and why.
3. Read the reading once, through `jq`, which keeps each lever's kind,
   id, and version and its figures, and nothing else:

   ```bash
   uv run acme-ops levers --env <env> --org <org_id> --days <days> \
     | jq -c '{since, until, sessions, spun, complete, standings: [.standings[] | {kind: .lever.kind, id: .lever.id, version: .lever.version, sessions, spun, sessions_without, spun_without, lift, spun_sessions}]}'
   ```

   An error printed instead, an empty answer, or one `jq` cannot parse
   ends the run: the report says the reading was not made, and why. A
   reading of 0 sessions is an answer: the org started none in the
   window, or the org is not known. No read is made a second time.
4. Judge each standing, in the order the reading gives, and give every
   one a verdict. A standing's `spun` is at least 1 and its `lift` above
   0, so one of these three fits each:
   - **finding**: `spun` of 2 or more and a `lift` of at least 0.25: the
     sessions that reached it stalled that much more often than the
     rest;
   - **weak**: `spun` of 2 or more and a `lift` below 0.25: it came
     before stalls, but not much more often than its absence did;
   - **too few**: `spun` of 1, too few to judge.

   A reading with `complete` false is judged on what it read, and the
   report says the window held more. When `spun` is 0, no session
   stalled, and the answer says so.
5. Write the report, with a proposed ticket for each finding. The
   ticket's work is a person's of the tenant, never this audit's: that
   person reads the lever's version (the portal shows the playbook or
   the entry with what its checks found) and the sessions named behind
   it, for a phrase said again and again, a must and a must-not on one
   subject, a tool its kinds do not hold, or a retry with no stopping
   condition, then publishes its next version. The audit proposes; it
   never fixes, and it never reads a lever's text or a session's
   content.

## What it never does

- Never writes to a shared database or to an environment: it reads the
  operator plane and writes its report under `~/Downloads/`.
- Never modifies a tracked file, never commits, never opens a pull
  request.
- No lever's name in the report or the conversation: the reading
  answers none, and each lever is named by its kind, id, and version.
- No session's content: the reading counts headers, and the audit opens
  no session.
- No token but the read one: the env file is sourced only in step 2 and
  never read, and a `write` operator stops the run.
- No cloud: no `aws` command. The operator plane is the one source.

## Output

`~/Downloads/acme_agent_levers_<yyyy-mm-dd>.md`:

```markdown
# Agent levers: <env>, org <org_id>, <since> to <until>

**Answer.** <one sentence: which lever came before the stalls, or that none did>

<sessions> sessions read, <spun> of them stalled<, and the window held more when complete is false>.

| Kind | Id | Version | Stalled with | Stalled without | Lift | Verdict |
|---|---|---|---|---|---|---|
| <playbook / knowledge> | <id> | <n> | <spun> of <sessions> | <spun_without> of <sessions_without> | <lift> | finding / weak / too few |

## Findings, by impact

1. <kind> <id> v<version>: <figures>; sessions <spun_sessions>; fix: a person of the tenant reads it and publishes its next version; effort <S/M/L>

## Proposed tickets

- <title>: <what, why, done-when>

## Not verified

- <the sessions and the steps past the reading's bound, when complete is false>
- <what each lever says, which the audit never reads>
```
