# ADR 2012: The model matrix is the engine's resolver, and a tenant's key reaches its call

**Status**: accepted (2026-10-03)

## Context

The engine never picks a model: an injected resolver turns a session's
model roles into fills, once, and a switch is a step of the history (ADR
1005). The platform decides for the whole fleet which model serves which
job, and changes that decision without a release of code. It also pays
a provider on a tenant's own key when the tenant holds one. Billing
refused every call of such a tenant, since the loop called on the
platform's key alone (ADR 2011).

## Decision

**One layer over the engine's models.** The engine's root takes one
models layer, or none. A layer answers three things: the resolver, a
face over the models manager every namespace reaches, and the client
each model call runs on with the name of its credential. The matrix is
that layer. The engine's resolver now hears which session it resolves
for, its models manager renews a fill set at the start of each loop, and
its loop and its compaction ask which client a call runs on. The engine
keeps its own answers: the table, no renewal, and the platform's key.

**The matrix is data, by version.** Its versions, the benchmark results,
and the retirements are global rows of the system scope; a version is
written once, pending, and publishing changes its status alone, in one
statement that also holds that no later version is published. A version
names the model roles it serves. A row names any of the five keys of a
question; the row that names the most keys among those that match wins,
and the spec's order of keys settles a tie, so no two rows ever tie.

**Filtered, then resolved.** What a session may not run on is taken out
of every row before a row is chosen: a fill its retention does not
admit, a retired model, and, for a tenant on its own keys, a provider it
holds no live key for. A row left empty answers nothing, and a less
specific one answers. A tenant on its own keys that holds a key for no
fill left gets the matrix's fill alone, whose call parks until a key is
saved, never a fallback on a key it lacks.

**Qualified by model and role.** A version is published only with the
row that matches everything, serving every model role the engine and
each kind the platform runs call, and with every fill priced by a row of
its own, not retired, and qualified by the latest recorded result of its
model for every role its row serves. A row that names no role serves
every role the version serves. Results are written once.

**A session is pinned.** Its first resolution that answers pins it to
the version published then, and one that answers nothing pins nothing,
so the next publication can answer it; a later publication changes
nothing a pinned session holds. At the
start of each loop, and never inside one, a fill whose model was retired,
or that a tightened retention no longer admits, switches to what the
latest version answers, and the session is pinned to that version. A
fallback a tightened retention no longer admits counts as tried.

**The tenant's key reaches its call.** Before each call the loop and the
compaction ask for the call's client by the tenant's funding: the
platform's key, or the tenant's live key for the provider, read per call.
The gate is told the credential the call carries. Billing holds an
account on its own key only for a call that carries a tenant key's
reference, which is a UUID, and an account the platform pays only for a
call that does not. The outage signal is kept under the credential the
call carried, and a compaction's failure names the key its call carried,
whichever is live by then. Only an authentication failure, a 401 or the
provider's own authentication error, refuses a tenant's key: it is marked
refused and its value kept, so every session that needs it parks on the
provider, naming the key, until the tenant saves a new one. Any other
credential error, such as a permission the key lacks, a region it
refuses, or a model its project cannot reach, parks only the session that
met it, naming a permission.

## Consequences

- No process wires the layer yet: a root opts in with
  `build_managers(models_layer=...)`, and builds the matrix managers over
  what it returns.
- A session parked for a missing or refused key wakes when a person
  resumes it; saving a key wakes nothing by itself.
- A tenant's own choice of fill holds while the session's pinned version
  qualifies it, its retention admits it, and the tenant holds its key.
  Otherwise the matrix answers.
