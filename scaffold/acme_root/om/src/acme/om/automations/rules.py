"""Pure rules of automations: whether a firing matches a trigger, where it
stands in a chain, and whether its limits let it run. Values in, values
out; both storage impls ask `admitted` inside the write that records a
run, so two firings at once cannot both take the last of a limit.

A firing passes these, in order, and the first that stops it says why:

- an act of the platform's account that names no recorded session is
  refused, since no hop can count its chain;
- an event its own session caused is ignored, unless the automation
  declares it wants them;
- a chain stops at its hop limit: a firing on an event a run's session
  caused is one hop past that run;
- the cost cap: each run reserves its run cap, and the runs of the period
  and the runs still at work never reserve past the automation's cap;
- the rate: the most firings that start in one period;
- the concurrency: the most runs at work at once.

The cost cap, the rate, and the concurrency queue a firing when the
automation says so; the other two refuse it for good."""

from datetime import datetime

from acme.om.automations.types.automation import (
    Automation,
    AutomationRun,
    Firing,
    Limits,
    Refusal,
    RunStatus,
    Tally,
    Trigger,
    TriggerKind,
)

QUEUEABLE = frozenset({Refusal.COST_CAP, Refusal.RATE, Refusal.CONCURRENCY})


def matches(trigger: Trigger, firing: Firing) -> bool:
    """Whether an event passes every filter the trigger sets. A schedule
    matches no event."""
    if trigger.kind is not TriggerKind.EVENT or firing.event_id is None:
        return False
    return (
        (not trigger.integrations or firing.integration in trigger.integrations)
        and (not trigger.arrivals or firing.arrival in trigger.arrivals)
        and (not trigger.effects or firing.effect in trigger.effects)
    )


def hop_after(cause: AutomationRun | None) -> int:
    """A firing's place in a chain: one past the run whose session caused
    its event, or the first hop when no run did."""
    return 1 if cause is None else cause.hop + 1


def ignored(automation: Automation, firing: Firing, cause: AutomationRun | None) -> Refusal | None:
    """Why a firing stops before any limit is asked: an act of the
    platform's account that names no recorded session, whose chain no hop
    can count; its own session's event; or a chain at its hop limit."""
    if firing.platform and firing.caused_by is None:
        return Refusal.UNATTRIBUTED
    own = cause is not None and cause.opened and cause.automation_id == automation.id
    if own and not automation.own_events:
        return Refusal.OWN_EVENT
    if hop_after(cause) > automation.limits.hop_limit:
        return Refusal.HOP_LIMIT
    return None


def limited(limits: Limits, tally: Tally) -> Refusal | None:
    """The limit that stops one more run, or None when it may start."""
    if tally.reserved_micros + limits.run_cap_micros > limits.cost_cap_micros:
        return Refusal.COST_CAP
    if tally.started >= limits.rate:
        return Refusal.RATE
    if tally.at_work >= limits.concurrency:
        return Refusal.CONCURRENCY
    return None


def admitted(run: AutomationRun, limits: Limits, tally: Tally, now: datetime) -> AutomationRun:
    """A run asking to start at `now`, as its limits leave it: started then,
    with its run cap reserved, queued when a limit stops it and the
    automation queues, or refused. Only a queued run keeps the event's
    text, which it needs when it starts; a refused one never does."""
    stop = limited(limits, tally)
    if stop is None:
        return run.model_copy(
            update={
                "status": RunStatus.STARTED,
                "refusal": None,
                "reserved_micros": limits.run_cap_micros,
                "started_at": now,
            }
        )
    queued = limits.queue and stop in QUEUEABLE
    return run.model_copy(
        update={
            "status": RunStatus.QUEUED if queued else RunStatus.REFUSED,
            "refusal": stop,
            "reserved_micros": 0,
            "event_text": run.event_text if queued else "",
        }
    )


def period_start(limits: Limits, now: datetime) -> datetime:
    return now - limits.period


def holds(run: AutomationRun, since: datetime) -> bool:
    """Whether a run counts against the cost cap at `since`: it started in
    the period, or it is still at work. A run counts from when it started,
    never from when it was queued, so a run queued in one period and
    started in the next counts in the next."""
    started = run.started_at
    return (
        run.status is RunStatus.STARTED
        and started is not None
        and (started >= since or run.closed_at is None)
    )


def tally(runs: list[AutomationRun], since: datetime) -> Tally:
    """What `runs`, an automation's started runs, hold at `since`."""
    started = [r for r in runs if r.status is RunStatus.STARTED and r.started_at is not None]
    return Tally(
        started=sum(r.started_at is not None and r.started_at >= since for r in started),
        reserved_micros=sum(r.reserved_micros for r in started if holds(r, since)),
        at_work=sum(r.closed_at is None for r in started),
    )


def slot(trigger: Trigger, anchor: datetime, now: datetime) -> datetime | None:
    """The time a schedule fires for at `now`: the latest of `anchor` and
    every `every` after it, at or before `now`. Every worker's tick in one
    slot names the same time, so the slot fires once however many ask; a
    slot that passed while no tick came is not fired late. None for an event
    trigger, or before the anchor."""
    if trigger.kind is not TriggerKind.SCHEDULE or trigger.every is None or now < anchor:
        return None
    return anchor + ((now - anchor) // trigger.every) * trigger.every
