---
name: ops-provider-outage
description: "Say which model provider and credential fail, in one environment, with a read-only credential: read the outage signal's reports and the line that names each provider and credential, and how many sessions park on a provider and for how long, then report the outage, its retry time, and its reach. Every read is an aggregate of the signals (Prometheus and the runner's log locally, CloudWatch in the cloud); never a tenant's rows, never the signal's store, never a write."
allowed-tools: Read, Grep, Bash(aws:*), Bash(curl:*), Bash(jq:*), Bash(uv run acme-ops size:*)
---

# ops-provider-outage

The investigator's skill for a provider that fails. When a call's
retries are spent, its runner reports an outage for the provider and
the credential it called with, and every session that would call the
same pair parks at once, naming the provider, until the retry time. A
tenant on its own key has a signal of its own. The runner writes one
line per report, and the sweep counts the parked sessions by reason
and age. This skill reads both.

Read `../_shared/ops-preamble.md`, a path from this skill's folder,
before the first step: the profiles, the account check, and the env
file are there.

## Input

`--env local|staging|production [--since 1h] [--log-file <path>]`

`--env` is required; ask for it when missing. `--since` is the window,
an hour by default; the run never widens it. `--log-file` is the
session runner's own output when it runs as a host process, which
keeps no log store of its own; without it, the local run reports the
log leg as "not read".

## Role and credential

The investigator: every signal, never a secret, and no tenant's rows.

`--env local` needs the compose stack with the `devx` profile up
(`make devx-up`) and the env file below. No cloud credential.

`--env staging` and `--env production` run under the investigate
profile of that environment, `acme-<env>-investigate`, checked with
`sts get-caller-identity` before any other command as the preamble
states. Refuse any profile wider than the investigate role. Every
`aws` command below carries `--profile acme-<env>-investigate`.

Locally the env file gives Prometheus's URL. Never read the env file;
a command that needs a value sources it in the same command, as every
block below does. Never print a token. The outage signal's store is
the shared cache, which no investigator logs in to: its reports are
read from the line each one writes.

## Procedure

1. In the cloud, check the profile as Role and credential states,
   before any other command; locally there is none to check. Then run
   `uv run acme-ops size --env <env>`, which refuses an env file that
   holds the provisioner's token. When it refuses, stop, and give the
   person the line it printed. Any other answer is not that refusal, the
   platform's size or an error of its own, and the run goes on.
2. Read the parks on a provider now, by age, and the outages reported
   in the window. Locally:

   ```bash
   set -a; . ~/.config/acme/ops/<env>.env; set +a
   curl -sG "$ACME_PROMETHEUS_URL/api/v1/query" \
     --data-urlencode 'query=sum by (age) (acme_sessions_parked{reason="provider"})'
   curl -sG "$ACME_PROMETHEUS_URL/api/v1/query" \
     --data-urlencode 'query=sum(increase(acme_outcomes_total{subsystem="outages",outcome="reported"}[<since>]))'
   ```

   In the cloud, the same two by the dashboard's schemas:

   ```bash
   aws cloudwatch get-metric-data --profile acme-<env>-investigate \
     --start-time <start> --end-time <end> --output text \
     --query 'MetricDataResults[?length(Values) > `0`].[Id,Label,max(Values),sum(Values)]' \
     --metric-data-queries '[
       {"Id":"parked","Period":60,"Label":"${PROP('"'"'Dim.reason'"'"')} ${PROP('"'"'Dim.age'"'"')}","Expression":"SEARCH('"'"'{\"Acme\",OTelLib,age,environment,reason,service} MetricName=\"acme_sessions_parked\" environment=\"<env>\" reason=\"provider\"'"'"', '"'"'Maximum'"'"', 60)"},
       {"Id":"reported","Period":60,"Label":"${PROP('"'"'Dim.outcome'"'"')}","Expression":"SEARCH('"'"'{\"Acme\",OTelLib,environment,outcome,service,subsystem} MetricName=\"acme_outcomes_total\" environment=\"<env>\" subsystem=\"outages\"'"'"', '"'"'Sum'"'"', 60)"}
     ]'
   ```

   A `parked` line is read by its last value, the sessions parked now;
   a `reported` line by its sum, the reports in the window.
3. Read which provider and credential each report names, from the line
   the runner writes, `outage reported: provider <p>, credential <c>,
   org <org>, until <retry_at>`. With `--log-file`, search it with `Grep`
   for `outage reported:`. In the cloud, the runner's log group,
   `/acme/<env>/session-runner`, holds the lines once an environment
   runs it; a group that does not exist is written as "not read":

   ```bash
   aws logs filter-log-events --profile acme-<env>-investigate \
     --log-group-name /acme/<env>/session-runner \
     --start-time <start ms> --filter-pattern '"outage reported:"' \
     --query 'events[].message' --output text
   ```

   The credential is `platform` for the platform's own key, or a tenant
   key's id: a name, never a value.
4. Find the reach: the parks on a provider now, by age, against the
   reports. Parks with no report in the window are older than it, or
   the provider refused the tenant's own key; parks `over_1d` old wait
   on more than an outage.
5. Write the report. A provider's own status page is the person's to
   read; this run reads the platform's signals alone.

## What it never does

- No write: no signal cleared, no session woken, no key changed. A
  session wakes at its retry time, staggered, by itself.
- No login to the shared cache, and no read of the signal's entries.
- No tenant's rows: the operator plane is not called; the parks are a
  count by reason and age.
- No secret value read or printed: a credential is named by `platform`
  or by its id.
- No second read of a count, and no wider window than `--since`.

## Output

```markdown
# Provider outage: <env>, the last <since>

**Credential.** <profile and Arn, or local>
**Reported.** <n> outage reports in the window
**Parked now.** <n> on a provider: <age: n, ...>

## Outages

- <provider>, credential <platform | key id>, <kind>, until <retry_at>
- or "not read: <why>" for the log leg

## Reach

<what the parks and the reports say together, one paragraph>
```
