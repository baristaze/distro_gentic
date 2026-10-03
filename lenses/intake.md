# Intake

Group id: `intake`. Covers Work In, Results Out of
`distro_gentic_spec.md`, and the promise What Closes a Loop makes that
feedback returns to the same session.

This group judges how the world's events reach a session and become
work: intake, the routing that finds a session and decides what wakes
it, twins in the suites, automations, playbooks and knowledge, and
notifications. It leaves the inbox and how data renders to the engine;
steering messages to `watch`; who may speak as a principal and how
outside text is labelled to `wall`; and the provenance a twin feeds into
evidence to `evidence`.

## INT-01 Events come in through the guideline's inbound queue

**Principle.** External events arrive through the guideline's inbound
queue; the platform adds the routing.

**Source.** Work In, Results Out, Intake.

**Look for.** Every handler that receives an external event, and what it
does before it answers.

**Violation.** A handler that routes the event, wakes a session, or
starts work inline instead of enqueueing it; an inbound path of the
platform's own beside the guideline's queue.

**Severity.** medium

**Check.** review

## INT-02 Feedback returns to the same session

**Principle.** A loop is closed when the world's answer to the result
comes back into the same session. A review comment reopens the work; it
never starts a conversation that has forgotten the old one. An event
finds its session by the pull request, the branch, or the session id it
names. A failing check wakes the session, and so does a ticket reopened
or reassigned to the agent.

**Source.** What Closes a Loop; Work In, Results Out, Feedback Routing.

**Look for.** How the router maps an event to a session; what an event
about delivered work does; what a failing check and a reopened ticket
do to a parked or an idle session.

**Violation.** Feedback on delivered work that starts a new session, or
a fresh history; an event matched to a session by anything but the pull
request, the branch, or the session id it names; a failing check, or a
ticket reopened or reassigned to the agent, that does not wake it.

**Severity.** high

**Check.** review

## INT-03 Only some feedback wakes the agent

**Principle.** Each arrival has its effect. A principal's message wakes
the session, and unarchives an archived one. A ticket reopened or
reassigned to the agent wakes it, and so does a failing check. A bot's
comment or a line of CI output waits in the inbox, read at the next
model call, and so does a passing check. Anything for an archived
session is recorded only.

**Source.** Work In, Results Out, Feedback Routing.

**Look for.** The router's table of arrivals and effects; what each
arrival does to a parked, an idle, and an archived session.

**Violation.** A bot's comment, CI output, or a passing check that wakes
the session; an arrival other than a principal's message that wakes an
archived session. (A failing check or a reopened ticket that does not
wake the session is INT-02.)

**Severity.** medium

**Check.** review

## INT-04 A comment instructs only from a mapped user who may instruct

**Principle.** A comment on the agent's work by a mapped user who may
instruct the session wakes it, as that principal's message. Any other
person's comment wakes it, as data.

**Source.** Work In, Results Out, Feedback Routing.

**Look for.** How the router decides that a commenter is a mapped user
who may instruct the session; how it marks a comment it delivers.

**Violation.** A comment from an unmapped user, or from a mapped user who
may not instruct the session, delivered as a principal's message. (How
outside text is labelled is WAL-04.)

**Severity.** high

**Check.** review

## INT-05 A person's push hands the session over

**Principle.** A person's push to the agent's branch hands the session
over: the agent stands down rather than fight them.

**Source.** Work In, Results Out, Feedback Routing.

**Look for.** What the router does with a push to the agent's branch by
anyone but the session.

**Violation.** A session that keeps working on its branch, or pushes
over, rewrites, or reverts a person's push to it.

**Severity.** medium

**Check.** review

## INT-06 Gating suites run twins, and acceptance runs apart

**Principle.** Every integration has the guideline's twin, which names
its provenance on every record and refuses to run outside `local`.
Gating suites run twins and the scripted model provider. Acceptance and
benchmarks run as a non-gating job, as the guideline's own benchmark
does: integrations as twins, the model on real providers.

**Source.** Work In, Results Out, Twins and Provenance.

**Look for.** Each integration's twin; what the gating suites run
against; how acceptance and benchmarks run.

**Violation.** An integration with no twin; a gating suite that reaches
a real integration or a real model provider; acceptance or a benchmark
wired as a gate on a code change. (A twin's record taken for real
evidence is EVD-03.)

**Severity.** medium

**Check.** review

## INT-07 An automation runs as its creator or the automation principal

**Principle.** Automations turn events into bounded work. A trigger, an
event with filters or a schedule, leads to an action: start a session,
or message a standing session. An automation runs as its creator or as
the tenant's automation principal.

**Source.** Work In, Results Out, Automations.

**Look for.** The principal each automation's action runs under.

**Violation.** An automation that acts as the system, as the agent, or as
the person whose event triggered it.

**Severity.** high

**Check.** review

## INT-08 An automation is bounded, and a chain stops at its hop limit

**Principle.** An automation has limits of its own: a cost cap, a rate,
a concurrency, and whether to queue when limited. It ignores the events
its own sessions caused, unless it declares otherwise, and a chain of
automations stops at a hop limit, so an agent's comment cannot start an
endless chain. Every firing is a recorded run. Autonomy stops exactly
where policy says: at an approval, a bound, or a limit.

**Source.** Work In, Results Out, Automations; What Closes a Loop.

**Look for.** An automation's limits, and where each is enforced; how it
knows an event its own sessions caused; the hop count a chain carries;
the record of each firing.

**Violation.** An automation without a cost cap, a rate, or a
concurrency, or one whose limits are not enforced; an automation that
fires on its own sessions' events without declaring it; a chain with no
hop count or no limit; a firing with no recorded run.

**Severity.** high

**Check.** review

## INT-09 Only a person publishes a playbook, and its gates only narrow

**Principle.** Playbooks are a team's procedures as versioned,
executable briefs, in the Agent Skills format with their gates in a
namespaced metadata extension. Only a person publishes a playbook. A
principal or an automation invokes one, and its gates compile into the
session's policy, where they can only narrow it.

**Source.** Work In, Results Out, Playbooks and Knowledge.

**Look for.** Who may publish a playbook; who may invoke one; how its
gates compile into the session's policy.

**Violation.** A playbook an agent publishes, or one run unversioned; a
playbook the agent invokes on its own; a gate that widens a session's
policy, adds a tool, or lifts an approval.

**Severity.** high

**Check.** review

## INT-10 Knowledge a person has not reviewed is never recalled

**Principle.** Knowledge is recalled into a session when its trigger
matches, so a new session does not rediscover its environment. It
renders as data. An agent may suggest knowledge, and a person reviews it
before any session recalls it, so one session cannot plant instructions
for the next.

**Source.** Work In, Results Out, Playbooks and Knowledge.

**Look for.** How knowledge is suggested, reviewed, and recalled; how
recalled knowledge renders.

**Violation.** An agent's suggestion recalled before a person reviews
it; recalled knowledge rendered as an instruction.

**Severity.** high

**Check.** review

## INT-11 A park that needs a person tells whoever can clear it

**Principle.** A park that needs a person notifies whoever can clear it
(the requester, eligible approvers, a budget's owner) on their channels,
with a link to the one action that clears it.

**Source.** Work In, Results Out, Notifications.

**Look for.** What a park that needs a person sends, to whom, and with
which link.

**Violation.** A park that needs a person and notifies no one, or only
people who cannot clear it; a notification with no link to the action
that clears it.

**Severity.** medium

**Check.** review
