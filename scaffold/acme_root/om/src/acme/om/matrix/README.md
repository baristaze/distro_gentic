# The model matrix

Which model does each job of each session, as the platform decides it
for the whole fleet. This is one of the kinds of thing [Acme is made
of](../../../../README.md).

## What it holds

- **Question**: what a session asks for each [model
  role](../models/README.md): the environment the platform runs in, the
  model role, the session's agent kind, its tenant's plan tier, and its
  workload class. A product names its sessions' workload classes; with
  none named, every session's is `standard`.
- **Row**: the fills that answer a set of questions, the first the fill
  and the rest its fallbacks. A row names any of the five keys and leaves
  the rest open. The row that names none matches every question.
- **Version**: the model roles the matrix serves and its rows, written
  once. It is pending until an operator publishes it, and the latest
  version published is the matrix. A change is a new version.
- **Benchmark result**: what a run of a benchmark showed of a model for
  one model role, as a person recorded it. The latest result for the two
  decides.
- **Retirement**: a model its provider retired.
- **Pin**: the version a session's fills came from, one for its first
  fill set and one for each switch the matrix made since.
- **Choice**: the fill a tenant on its own keys chose for one model role.

## What can happen

- **Stage and publish.** An operator stages a version, then publishes it
  once every fill in it is priced and qualified, and a row matches every
  question. Each reason it may not be published is named.
- **Record.** An operator records a benchmark's result, or a provider's
  retirement of a model. No code change waits on either.
- **Resolve.** A session's first loop resolves its fills at the version
  published then, and pins the session to it once it answers; one that
  answers nothing pins nothing. What the session may not
  run on is taken out first: a fill its tenant's retention does not
  admit, a retired model, and, for a tenant on its own keys, a provider
  it holds no key for. The most specific row with a fill left answers.
- **Renew.** At the start of each loop, a fill whose model was retired
  switches to what the latest version answers now, by a `switched` step,
  and the session is pinned to that version.
- **Call on the tenant's key.** Each model call of a tenant on its own
  keys goes out on its live key for the provider, read per call. A key
  the provider does not authenticate is marked refused, so every session
  that needs it waits for a new one; a permission the key lacks parks only
  the session that met it.
- **Choose.** A tenant on its own keys chooses a fill for a model role,
  or drops its choice.
- **Count.** Each settled model call counts its tokens and its spend
  under the version its session is pinned to, a published one, so the
  operator's dashboard reads spend by version; a session pinned to none
  counts under `none`.

## The rules

- **Every question has an answer.** No version is published without the
  row that matches everything, or without a model role the engine or a
  kind the platform runs calls. Of the rows that match, the one that names
  the most keys wins, and of two that name as many, the one that names the
  earlier key, in the order above.
- **A model enters priced and qualified.** Each fill of a published
  version has a price row of its own and a passing benchmark for every
  model role its row serves, and names no retired model.
- **A session keeps its version.** A publication changes no running
  session's fills. Only a retirement switches one, and only between loops.
- **Eligibility filters resolution.** A tenant that keeps nothing, or
  stays in one region, resolves only to fills that do, fallbacks
  included, and its fill set holds that requirement.
- **A tenant's key, alone.** A call that needs a tenant's key runs on it
  or not at all; a session whose tenant lacks the key parks until one is
  saved. Its outage signal is its key's own.
- **A tenant never names a model** unless it pays its providers itself,
  and then only among the fills the matrix qualified for that role, from
  a provider it holds a key for.
- **The matrix is the platform's.** Its versions and records belong to no
  org. A pin and a choice belong to one org, and go with it.

<!-- agents-only
The layer is `root.MatrixLayer`, a `models.layer.ModelsLayerInterface`
that a root hands `build_managers(models_layer=...)`: `impl/resolver.py`
is the engine's resolver, `impl/models.py` the face over the engine's
models manager (eligibility from the retention snapshot, renewal, and the
purge of pins and choices), and `impl/credentials.py` the call credentials
the loop and a compaction ask. The pure rules are `rules.py`. ADR 2012
records the decisions.
-->

## How another namespace composes it

The engine's loop resolves a session's fills through the matrix, renews
them at each new loop, and asks before each call which key it goes out
on. [Billing](../billing/README.md) holds a call on a tenant's own key
only when the call carries that key. The tenant's keys are
[trust](../trust/README.md)'s, and its retention
[retention](../retention/README.md)'s.
