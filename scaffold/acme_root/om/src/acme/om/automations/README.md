# Automations

Events turned into bounded work. This is one of the kinds of thing [Acme
is made of](../../../../README.md).

## What it holds

- **Automation**: a trigger (an event with filters, or a schedule), an
  action (start a session, or message a standing one), and limits of its
  own: a cost cap over a period and the share one run may take, a rate,
  a concurrency, whether to queue when limited, and a hop limit. It runs
  as its creator.
- **Run**: the record of one firing: started, queued, or refused, and
  why; its place in a chain; the session it started or messaged; and the
  budget that holds a started session to its share.

## What can happen

- **Create** an automation, by a person in person.
- **Fire.** An event the router placed fires every enabled automation
  whose filters it passes. Each firing is a run.
- **Tick.** A schedule that is due fires, and queued runs start while
  the limits let them.

## The rules

- **An automation ignores its own sessions' events,** unless it says it
  wants them. An event's session is the one whose recorded act it
  follows, whatever session it reaches, and else the session whose work
  it lands on.
- **A chain stops at its hop limit.** A firing on an event a run's
  session caused is one hop past that run. An act of the platform's
  account that names no recorded session fires nothing.
- **The cost cap holds.** Each started run reserves its share, and a
  budget on the run's tree stops its spending there; the runs of a
  period and the runs still at work never reserve past the cap.
- **The rate and the concurrency hold,** and a firing they stop is
  queued or refused, as the automation says. A run counts in the period
  it starts in, however long it was queued.
- **A run keeps the event's text only while it is queued.** The
  session it starts holds it from then on.
- **It runs as its creator,** read live at each firing: a creator who
  left fires nothing.
- **The brief is the creator's word; the event is data.**
- **Every firing is a recorded run,** and one event makes one run.

<!-- agents-only
The limits are asked inside the write that records a run
(`AutomationStorageInterface.admit`, which holds the automation's row in
Postgres), from `rules.admitted`. A started session's tree gets a
`LIFE` budget of `run_cap_micros` before its brief wakes it.
-->

## How another namespace composes it

The delivery consumer fires automations with what
[intake](../intake/README.md) answered for an event: its effect, its
text as the agent reads it, and the session whose own act it was.
