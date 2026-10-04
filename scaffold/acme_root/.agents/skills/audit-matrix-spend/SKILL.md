---
name: audit-matrix-spend
description: "Audit what the platform's model calls spend, in one environment, with a read-only credential: the spend by matrix version, the prompt tokens read from a cache, written to one, and sent uncached, the hit rate by matrix version, and what rebuilt caches cost, over a window; then a report with verdicts and proposed tickets. Every read is an aggregate of the signals (Prometheus locally, CloudWatch in the cloud), the same series the operator dashboard draws. Never changes anything."
allowed-tools: Read, Grep, Glob, Write, Bash(aws:*), Bash(curl:*), Bash(jq:*), Bash(mkdir:*), Bash(uv run acme-ops size:*)
---

# audit-matrix-spend

Where the model money goes, and how much of it a cache could have
saved. Every settled model call counts its prompt tokens by how they
were billed (read from a cache, written to one, or sent uncached), its
output, and its reference cost, each by the matrix version its session
was pinned to: `none` when no matrix pinned it. A cache read is the
cheap token; a cache write is a cache rebuilt, paid above
the uncached rate. A fall in the hit rate is a cache that is rebuilt,
which the dashboard shows before the bill does.

Read `../_shared/ops-preamble.md`, a path from this skill's folder,
before the first step: the profiles, the account check, and the env
file are there.

## Input

`--env local|staging|production [--since 7d]`

`--env` is required; ask for it when missing. `--since` is the window,
seven days by default.

## Role and credential

Investigator, read-only, and no tenant's rows: every number is a
series by matrix version, plan tier, and kind of token, never by tenant. `--env local` needs
the compose stack with the `devx` profile up (`make devx-up`) and the
env file; no cloud credential. `--env staging` and `--env production`
run under `acme-<env>-investigate`, checked with
`sts get-caller-identity` before any other `aws` command, as the
preamble states. Refuse any profile wider than the investigate role.

Locally the env file gives Prometheus's URL. Never read the env file;
a command that needs a value sources it in the same command, as every
block below does. Never print a token.

## Procedure

1. In the cloud, check the profile as Role and credential states,
   before any other command; locally there is none to check. Then run
   `uv run acme-ops size --env <env>`, which refuses an env file that
   holds the provisioner's token. When it refuses, stop, and give the
   person the line it printed. Any other answer is not that refusal, the
   platform's size or an error of its own, and the run goes on. Make
   the report's folder, `~/Downloads/acme_matrix_spend_<yyyy-mm-dd>/`
   (`mkdir -p`).
2. Read the window's spend by matrix version and plan tier, and its
   tokens by matrix version, plan tier, and kind, once each. Locally:

   ```bash
   set -a; . ~/.config/acme/ops/<env>.env; set +a
   curl -sG "$ACME_PROMETHEUS_URL/api/v1/query" \
     --data-urlencode 'query=sum by (matrix_version, plan_tier) (increase(acme_model_spend_micros_total[<since>])) / 1e6'
   curl -sG "$ACME_PROMETHEUS_URL/api/v1/query" \
     --data-urlencode 'query=sum by (matrix_version, plan_tier, kind) (increase(acme_model_tokens_total[<since>]))'
   ```

   In the cloud, by the dashboard's schemas, an hour a datapoint:

   ```bash
   aws cloudwatch get-metric-data --profile acme-<env>-investigate \
     --start-time <start> --end-time <end> --output text \
     --query 'MetricDataResults[?length(Values) > `0`].[Id,Label,sum(Values)]' \
     --metric-data-queries '[
       {"Id":"spend","Period":3600,"Label":"${PROP('"'"'Dim.matrix_version'"'"')} ${PROP('"'"'Dim.plan_tier'"'"')}","Expression":"SEARCH('"'"'{\"Acme\",OTelLib,environment,matrix_version,plan_tier,service} MetricName=\"acme_model_spend_micros_total\" environment=\"<env>\"'"'"', '"'"'Sum'"'"', 3600)"},
       {"Id":"tokens","Period":3600,"Label":"${PROP('"'"'Dim.matrix_version'"'"')} ${PROP('"'"'Dim.plan_tier'"'"')} ${PROP('"'"'Dim.kind'"'"')}","Expression":"SEARCH('"'"'{\"Acme\",OTelLib,environment,kind,matrix_version,plan_tier,service} MetricName=\"acme_model_tokens_total\" environment=\"<env>\"'"'"', '"'"'Sum'"'"', 3600)"}
     ]'
   ```

   A `spend` line is millionths of a dollar; divide by 1,000,000. A
   query that answers nothing is written as "none in the window", never
   read again with a wider window.
3. Compute, for each (matrix version, plan tier) pair on its own: the
   hit rate, `cache_read / (input + cache_read + cache_write)`; the
   share of the prompt written to a cache,
   `cache_write / (input + cache_read + cache_write)`; and the spend's
   share of the whole. The price of a cache write against an uncached
   token is the price table's, in `om/src/acme/om/budgets/` (read it
   with `Read`), so the cost of rebuilt caches is the cache writes at
   the write rate's premium over the input rate, per pair, as an
   estimate the report labels so. Each version's total across its tiers
   is reported beside its pairs.
4. Judge each (matrix version, plan tier) pair: a hit rate under half,
   or cache writes above a tenth of the prompt, is a finding; so is a
   pair whose spend share is far above its share of tokens. `none` is
   every call whose session no matrix pinned, judged the same way, tier
   by tier.
5. Write the report, with each finding's proposed ticket: what to
   change (a prompt's stable prefix, a cache breakpoint, a fill), the
   evidence, and the effort. The audit proposes; it never fixes.

## What it never does

- Never writes to a shared database or to an environment: it reads
  aggregates and writes its report under `~/Downloads/`.
- Never modifies a tracked file, never commits, never opens a pull
  request.
- No tenant's rows and no series by tenant: the matrix version is the
  finest cut.
- No secret value read or printed: the env file is sourced and never
  read.

## Output

`~/Downloads/acme_matrix_spend_<yyyy-mm-dd>.md`:

```markdown
# Model spend: <env>, the last <since>

**Answer.** <one sentence: where the money goes, and what a cache would save>

| Matrix version | Spend ($) | Share | Hit rate | Cache writes | Verdict |
|---|---|---|---|---|---|
| <version or none> | <n> | <p>% | <p>% | <p>% of prompt | ok / finding |

## Findings, by impact

1. <finding>: <evidence>; fix: <change>; effort <S/M/L>

## Proposed tickets

- <title>: <what, why, done-when>

## Not verified

- <anything else the run could not read>
```
