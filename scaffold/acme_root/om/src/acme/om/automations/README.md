# Automations

Events turned into bounded work. This is one of the kinds of thing [Acme
is made of](../../../../README.md).

## What it holds

- **Automation**: a trigger (an event with filters, or a schedule), an
  action (start a session in one of the tenant's
  [projects](../projects/README.md), message a standing one, or a
  product's own kind of action), and
  limits of its own: a cost cap over a period and the share one run may take, a rate,
  a concurrency, whether to queue when limited and how deep, and a hop
  limit. It runs
  as its creator, or as the tenant's automation principal.
- **Automation principal**: a service principal the tenant grants, one a
  tenant, holding one role.
- **Run**: the record of one firing: started, queued, or refused, and
  why; its place in a chain; the session it started or messaged, or the
  work a product's action started and how it ended; and the budget that
  holds a started session to its share.

## What can happen

- **Create** an automation, by a person in person. A start names a
  project of the tenant; outside a local stack, one that names none is
  refused. A product's action names a kind the product declares, and its
  params hold to that kind's shape; any other is refused.
- **Edit** an automation, by a person in person, held to the create's
  checks. One that runs as its creator is edited by its creator alone.
  One that runs as the automation principal takes its editor as its
  creator, so the grant is held to the editor's role at each firing.
- **Grant** the automation principal a role, by a person who manages the
  tenant's members, in person, never above their own role. A second
  grant changes the role and keeps the principal.
- **Fire.** An event the router placed fires every enabled automation
  whose filters it passes. Each firing is a run.
- **Tick.** Every worker's sweep ticks each tenant once a pass. A
  schedule fires once for the slot it is in, its creation time and every
  period after it, whichever worker ticks first; a slot no tick reached
  is not fired late. Queued runs start while the limits let them. A
  schedule's period is a minute at least, and one automation that fails
  its tick never stops the others.

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
- **A queue holds at most its depth.** A firing that finds it full is
  refused, and says so; a run already queued keeps its place. The depth
  is read in the write that admits the run, so two firings at once never
  both take its last place.
- **A run keeps the event's text only while it is queued.** The
  session it starts holds it from then on.
- **It runs as its creator,** read live at each firing: a creator who
  left fires nothing. **Or as the automation principal,** whose grant is
  read at each firing and at each call its sessions make: they hold that
  role's authority and no more, never the creator's and never the
  service role's. One is made only once a principal is granted, and
  only by a person whose role is at least the grant. A firing is
  refused, and starts no session, when the grant is above its creator's
  role then or its creator left. The check is at the firing: a session
  already running when the grant is raised, or its creator moved below
  it, makes its remaining calls at the grant.
- **A slot fires once.** Its run's id is derived from the automation and
  the slot, so several workers at once make one run.
- **A started session is in its project from its first moment,** so the
  project's budget and policies hold it. Another tenant's project is
  refused when the automation is saved. Outside a local stack, a start
  that names no project is refused when it is saved, and one stored
  with none starts nothing when it fires: its run is refused, and says
  why.
- **A product adds its own kind of action, and never takes the
  platform's.** Its kind acts in the firing, as the automation runs, and
  its check says when the work it started ended: the run is at work
  until then, however long that takes, and closes succeeded or failed as
  the check says. A check that fails leaves the run open. A kind named as
  one of the platform's actions, or twice, is refused at boot, and an
  automation whose kind left the product is refused at each firing.
- **The brief is the creator's word; the event is data.**
- **Every firing is a recorded run,** and one event makes one run.

<!-- agents-only
The limits are asked inside the write that records a run
(`AutomationStorageInterface.admit`, which holds the automation's row in
Postgres), from `rules.admitted`. A started session's tree gets a
`LIFE` budget of `run_cap_micros` before its brief wakes it, and starts
through the projects' `start_session`. `build_automations` takes
`project_required`, which a root sets outside `local`, and `actions`,
the product's kinds (`ProductKinds.actions`, `actions.py`), which every
process that writes or fires an automation hands it. The
principal's live context is `root.automation_principals`, the transition
a root hands `build_managers` too, so its sessions' calls are answered by
the grant. A slot is `rules.slot`; ADR 2017 has the reasons, and ADR
2031 those of a product's action.
-->

## How another namespace composes it

The delivery consumer fires automations with what
[intake](../intake/README.md) answered for an event: its effect, its
text as the agent reads it, and the session whose own act it was.
