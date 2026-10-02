---
name: ops-integration-silent
description: "Say why an integration's events stopped arriving, in one environment, with a read-only credential: read the deliveries its route answered by status (a refused signature is a 401), what the worker made of each delivery, and the queue's dead letters, match them against one table of causes, and report the cause and the next step. Every read is an aggregate of the signals (Prometheus locally, CloudWatch in the cloud); never a tenant's rows, never a write."
allowed-tools: Read, Bash(aws:*), Bash(curl:*), Bash(jq:*), Bash(uv run acme-ops size:*)
---

# ops-integration-silent

The investigator's skill for an integration that went quiet. An
integration's events arrive as signed deliveries at its route, which
checks the signature and queues each one; the worker then applies it.
Silence has three places to be: nothing arrives, deliveries arrive and
are refused, or they are queued and fail. The signals count all three,
and this skill reads those counts, never a delivery's body.

The integration the tree holds is the identity provider's, at
`/webhooks/identity`, queued on the `webhooks` queue. Another
integration that adds a route reads the same way, by its route.

Read `../_shared/ops-preamble.md`, a path from this skill's folder,
before the first step: the profiles, the account check, and the env
file are there.

## Input

`--env local|staging|production [--route /webhooks/identity] [--since 6h]`

`--env` is required; ask for it when missing. `--route` is the
integration's route, the identity provider's by default. `--since` is
the window, six hours by default; the run never widens it.

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
block below does. Never print a token.

## Procedure

1. Run `uv run acme-ops size --env <env>`, which refuses an env file
   that holds the provisioner's token. When it refuses, stop, and give
   the person the line it printed. Any other answer is not that refusal,
   the platform's size or an error of its own, and the run goes on. In the cloud, check the profile as
   Role and credential states.
2. Read the three counts over the window, once each. Locally:

   ```bash
   set -a; . ~/.config/acme/ops/<env>.env; set +a
   curl -sG "$ACME_PROMETHEUS_URL/api/v1/query" \
     --data-urlencode 'query=sum by (status) (increase(acme_http_requests_total{route="<route>"}[<since>]))'
   curl -sG "$ACME_PROMETHEUS_URL/api/v1/query" \
     --data-urlencode 'query=sum by (outcome) (increase(acme_outcomes_total{subsystem=~"deliveries|queue"}[<since>]))'
   ```

   In the cloud, the same counts by the dashboard's schemas, and the
   dead-letter queue's depth:

   ```bash
   aws cloudwatch get-metric-data --profile acme-<env>-investigate \
     --start-time <start> --end-time <end> --output text \
     --query 'MetricDataResults[?length(Values) > `0`].[Id,Label,sum(Values),max(Values)]' \
     --metric-data-queries '[
       {"Id":"route","Period":60,"Label":"${PROP('"'"'Dim.status'"'"')} ${PROP('"'"'Dim.route'"'"')}","Expression":"SEARCH('"'"'{\"Acme\",OTelLib,environment,method,route,service,status} MetricName=\"acme_http_requests_total\" environment=\"<env>\" route=\"<route>\"'"'"', '"'"'Sum'"'"', 60)"},
       {"Id":"out","Period":60,"Label":"${PROP('"'"'Dim.subsystem'"'"')} ${PROP('"'"'Dim.outcome'"'"')}","Expression":"SEARCH('"'"'{\"Acme\",OTelLib,environment,outcome,service,subsystem} MetricName=\"acme_outcomes_total\" environment=\"<env>\" subsystem=\"deliveries\"'"'"', '"'"'Sum'"'"', 60)"},
       {"Id":"dead","Label":"dead letters","MetricStat":{"Metric":{"Namespace":"AWS/SQS","MetricName":"ApproximateNumberOfMessagesVisible","Dimensions":[{"Name":"QueueName","Value":"acme-<env>-webhooks-dead"}]},"Period":60,"Stat":"Maximum"}}
     ]'
   ```

   A query that answers nothing is written as "none in the window",
   never read again with a wider window. An answer that is an error,
   empty, or not JSON is written as "not read", naming it.
3. Find the cause: the first row whose condition holds, top to bottom.

   | Condition | Cause | Next |
   |---|---|---|
   | The route answered nothing in the window | Nothing arrives: the provider stopped sending, or sends elsewhere; its own dashboard says which | the provider's delivery settings, by a person |
   | The route answered `401` or `400`, and few or no `2xx` | Deliveries arrive and their signature is refused: the signing secret changed on one side | the integration's secret, by a person, through the pipeline |
   | The route answered `503` or `5xx` | The route itself fails before it queues | `ops-investigate` over the same window |
   | `deliveries` counts `failed` or `receive_failed`, or the dead letters are above 0 | Deliveries are queued and the worker fails them | `ops-root-cause` with a failed delivery's request id |
   | otherwise | Deliveries arrive and are applied: the silence is downstream of the integration | `ops-investigate` |

4. Write the report.

## What it never does

- No write: no redrive of the dead-letter queue, no resend, no change
  of a secret. Each is a person's, through the pipeline.
- No delivery's body read: only counts.
- No tenant's rows: the operator plane is not called.
- No secret value read or printed: the env file is sourced and never
  read.
- No second read of a count, and no wider window than `--since`.

## Output

```markdown
# Integration silent: <env>, <route>, the last <since>

**Credential.** <profile and Arn, or local>
**Arrived.** <status: count, ...> or none in the window
**Applied.** <outcome: count, ...>; dead letters <n | not read>

## Cause

<the table's row, with the counts that decided it>

## Next

<the next step the row names>
```
