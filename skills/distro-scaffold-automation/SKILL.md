---
name: distro-scaffold-automation
description: "Add an automation trigger: a kind of trigger beside the event and the schedule, fired by an occurrence a namespace records, with its filters on the trigger, its pure match rule, the work item that carries each occurrence to one firing, and its tests, so the limits, the own-events rule, and the hop limit hold for it as for every trigger, in the shape of the event trigger and the delivery that fires it. Python."
allowed-tools: Read, Grep, Glob, Write, Edit, Bash(make check), Bash(uv run:*), Bash(git status:*), Bash(git show:*)
---

# distro-scaffold-automation

A path that starts with `../` is read from this skill's folder as
`realpath` resolves it.
Conventions: `../_shared/scaffold-conventions.md`.
Sections of `../../distro_gentic_spec.md`: Work In, Results Out
(Automations, Feedback Routing), Money (Metering and Limits), Failure at
Fleet Scale.
Lenses: `../../lenses/intake.md`, and `../../lenses/fleet.md` for what
fires on time.

## Input

`<trigger> --occurrence <namespace>.<what> [--filters <field,...>]`,
and what the trigger fires on, in the arguments or in the conversation.

Example: `session_ended --occurrence agent_sessions.ended --filters agent_kinds,outcomes`,
for "a session of a named kind that ends with a named outcome starts a
session of another kind".

- `<trigger>` is the trigger's kind, snake case, the value of its
  `TriggerKind` member. `<TRIGGER>` is the member's name.
- `--occurrence` names the write that records what fires it: the
  namespace and the manager operation whose commit the trigger follows.
  It is a write of the tree, never a message from outside: an external
  system's event is an integration's (`distro-scaffold-integration`)
  and reaches automations as an `event` trigger.
- `--filters`: the fields of an occurrence a trigger of the kind may
  name values for. A filter left empty matches any occurrence, as the
  event trigger's do.

## Created

The shape of a trigger is the event trigger: `TriggerKind.EVENT` and
the filters of `Trigger` in
`om/src/<name>/om/automations/types/automation.py`, matched by `matches`
in `om/src/<name>/om/automations/rules.py`, and fired by
`FeedbackDeliveriesImpl.apply` in
`workers/maintenance/src/<name>/workers/maintenance/deliveries.py`,
which builds a `Firing` and calls `fire`.

| File | Holds |
|------|-------|
| `workers/maintenance/src/<name>/workers/maintenance/<trigger>.py` | the handler of the work kind of step 3, which builds the `Firing` and calls `fire` |
| `workers/maintenance/tests/test_<trigger>.py` | the handler's cases of step 5 |

## Changed

| File | Change |
|------|--------|
| `om/src/<name>/om/automations/types/automation.py` | `TriggerKind.<TRIGGER>`; each filter on `Trigger`; in `_a_schedule_has_a_period` or a validator beside it, a trigger of the kind sets its own filters alone and no `every`; on `Firing`, the fields its filters read, defaulted so the existing callers change nothing |
| `om/src/<name>/om/automations/rules.py` | `matches` answers for the kind by its filters, and a firing of one kind never matches a trigger of another |
| the namespace of `--occurrence`, its manager impl | the work item asked for in the occurrence's own write |
| `om/src/<name>/om/work/` and `workers/maintenance/src/<name>/workers/maintenance/main.py` | the work kind, its payload, and its handler in `handlers` of `build_loop`, as the worker's README says under Adding a work kind |
| `om/tests/unit/test_automations.py` | the cases of step 5 for the rule and the manager |
| `om/src/<name>/om/automations/README.md` | the kind in What it holds and What can happen |

## Procedure

1. Everything an automation does once it fires is the manager's and
   stays as it is: who it runs as, its limits and whether it queues,
   the own-events rule (`own_events`), the hop limit, and the run it
   records whatever became of it (`fire` and `_fire_one` in
   `om/src/<name>/om/automations/impl/manager.py`). A new kind adds what
   fires it and what it matches, never a path around them.
2. The rule is pure: `matches(trigger, firing)` reads only the two, and
   a schedule still matches no occurrence. The trigger's fields are
   `Stored` values a person sets, checked against the values the
   occurrence can carry where those are a closed set.
3. An occurrence reaches `fire` once, after the write that records it
   commits: that write asks for a work item in its own transaction, as a
   pending session asks for a `LOOP` item, and the maintenance worker's
   handler fires it. Never call `fire` from inside the occurrence's
   write: a firing that rolls back with it, or one that fires for a
   write that never commits, is a run the record cannot explain.
4. The handler builds the `Firing` with the occurrence's own id as
   `event_id` and its time as `occurred_at`, so a retried item makes the
   run it made the first time, and with `caused_by`, the session whose
   act the occurrence is, so an automation that started that session
   ignores it unless it says otherwise and a chain stops at its hop
   limit. Its text is data: a started session reads it as the event's,
   never as an instruction. It runs under the tenant's service context
   the claim built, and names the permissions it calls with
   (`REQUIRES`).
5. The tests, over the fixtures of `om/tests/unit/test_automations.py`
   (`automation`, `limits`, `made`, `platform`, `creator`):
   - a trigger of the kind matches an occurrence that passes each filter
     it sets and no other, an empty filter matches any, and a trigger of
     another kind never matches it;
   - a trigger that sets `every` or another kind's filters is refused;
   - an occurrence fires each matching automation once, and the same
     occurrence fired again makes no second run;
   - an occurrence its automation's own session caused is ignored, and
     one past the hop limit is refused, both recorded as runs;
   - a firing past a limit queues or is refused, as the automation's
     `queue` says;
   - the work item is asked for in the occurrence's write, and its
     handler fires once for a redelivered item, shape
     `workers/maintenance/tests/test_deliveries.py`.

Then the gate, `make check`, as After writing in the conventions
runs it.

## Output

As `../_shared/scaffold-conventions.md` states.
