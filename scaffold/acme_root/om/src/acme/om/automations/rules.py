"""Pure rules of automations: whether a firing matches a trigger, where it
stands in a chain, and whether its limits let it run. Values in, values
out; both storage impls ask `admitted` inside the write that records a
run, so two firings at once cannot both take the last of a limit.

A firing passes these, in order, and the first that stops it says why:

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


def ignored(automation: Automation, cause: AutomationRun | None) -> Refusal | None:
    """Why a firing stops before any limit is asked: its own session's
    event, or a chain at its hop limit."""
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


def admitted(run: AutomationRun, limits: Limits, tally: Tally) -> AutomationRun:
    """A run asking to start, as its limits leave it: started with its run
    cap reserved, queued when a limit stops it and the automation queues,
    or refused."""
    stop = limited(limits, tally)
    if stop is None:
        return run.model_copy(
            update={
                "status": RunStatus.STARTED,
                "refusal": None,
                "reserved_micros": limits.run_cap_micros,
            }
        )
    status = RunStatus.QUEUED if limits.queue and stop in QUEUEABLE else RunStatus.REFUSED
    return run.model_copy(update={"status": status, "refusal": stop, "reserved_micros": 0})


def period_start(limits: Limits, now: datetime) -> datetime:
    return now - limits.period


def holds(run: AutomationRun, since: datetime) -> bool:
    """Whether a run counts against the cost cap at `since`: it started in
    the period, or it is still at work."""
    return run.status is RunStatus.STARTED and (run.created_at >= since or run.closed_at is None)


def tally(runs: list[AutomationRun], since: datetime) -> Tally:
    """What `runs`, an automation's started runs, hold at `since`."""
    started = [run for run in runs if run.status is RunStatus.STARTED]
    return Tally(
        started=sum(run.created_at >= since for run in started),
        reserved_micros=sum(run.reserved_micros for run in started if holds(run, since)),
        at_work=sum(run.closed_at is None for run in started),
    )


def due(trigger: Trigger, last: datetime | None, now: datetime) -> bool:
    """Whether a schedule fires now: it never has, or `every` has passed
    since it last did."""
    if trigger.kind is not TriggerKind.SCHEDULE or trigger.every is None:
        return False
    return last is None or now - last >= trigger.every
