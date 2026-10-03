# The platform's agents

The agents the platform ships, and the one session it runs with no agent
at all. This is one of the kinds of thing [Acme is made
of](../../../../README.md).

Every agent here is a kind of the one [loop](../agents/README.md): a
profile with its own powers. A profile names the tools the agent may
call, when its work is done, whose authority its calls run under, the
workspace it works in, and which of its calls run without asking.

## What it holds

- **The engineer** takes an objective to a validated, reviewable change.
  It works in a container of its own, from which nothing leaves: it reads
  and writes files and runs commands. It asks for a validation of its
  committed head on a fresh executor, opens its pull request on its own
  branch, and submits its result through the
  [result gate](../evidence/README.md), citing the runs that validation
  wrote. A success counts only when the validation at its head passed.
- **Analysis** reads what a run produced (its logs, telemetry,
  recordings, and sensor data) in a workspace of its own, changes
  nothing, and answers with its findings.
- **The planner** turns findings into tasks. It reads where sessions
  stand, hands new engineering work to an engineer, and answers with its
  plan: each task and the session it goes to.
- **The platform assistant** helps the people who set up and run their
  part of the platform, on their own permissions. It explains the
  product from its corpus and cites it, diagnoses where a session stands
  by reading it, drafts the tenant's tool policy and shows the difference
  from what is live, and hands engineering work to an engineer. It has no
  workspace, repository, shell, or station.
- **The corpus**: what the [knowledge map](../../../../../llms.txt) lists
  for the tenant's users, read once when the process starts. A document
  listed only for the platform's own people is not in it.
- **A validation session**: one check run on a station of a lab, with no
  agent. It holds the check, its version, its parameters, and its lab,
  and, once its run is recorded, which run it was.

## What can happen

- **Ask the assistant.** A person types in an assistant's session. It
  searches the corpus, reads live state, drafts, or hands work on, and
  answers.
- **Hand work on.** The assistant or the planner starts an engineer
  session with an objective that stands on its own. The new session
  names where it came from, holds only the objective, and starts when its
  person confirms it. The agent that handed it on cannot steer it.
- **Apply a draft.** A person who manages the tenant writes the policy a
  draft holds, at the version the draft was drawn from. A policy changed
  since is refused, never written over.
- **Open a pull request.** The engineer's `open_pull_request` takes a
  title and a body, and nothing else. The workspace's committed head goes
  to the session's own branch on its project's repository, with a push
  token the workspaces mint for the call and check before each write
  ([ADR 2022](../../../../../docs/adr/2022-a-repositorys-credentials-are-the-platforms-and-the-agent-never-holds-one.md)).
  The model never sees the token, and names neither the branch nor the
  repository. A second call moves the branch and keeps the one pull
  request. The platform's account pushes for every session, so the head
  is recorded as the session's act, and the branch bound to it, before
  the push, and the pull request once it opens: a comment, a check, or a
  person's push on either finds the session ([intake](../intake/README.md)).
- **Start a validation session.** Its station work goes on its lab's
  lane of the [work queue](../work/README.md) in the same write, and the
  lab's daemon claims it through the gateway, as it claims any station
  work.
- **Finish it.** The daemon's run is recorded as an execution record,
  the record every run is, and the session names it. A session runs its
  check once.
- **Purge.** A tenant deleted past its retention loses its validation
  sessions.

## The rules

- **The assistant only reads and hands on.** Its authority is
  delegated, it has no workspace, and each of its tools reads or starts a
  session. A profile of it that names any other tool, or a catalog with
  two tools of one name, is refused when the process starts.
- **A draft changes nothing.** The assistant cannot apply
  configuration; a person does.
- **The corpus is the map's list for the tenant's users,** by listing,
  never by folder. A line that leads out of the repository is no
  document.
- **A validation session calls no model.** It is a record of its own,
  never an agent session, and asks for no loop, so no runner claims it
  and nothing is spent on it ([ADR
  2013](../../../../../docs/adr/2013-a-validation-session-is-station-work-with-a-record-of-its-own.md)).
- **Nothing routes.** A person chooses an agent by choosing the session
  they type in.
- **Every validation session belongs to one org.**

## How another namespace composes it

A process ships these agents by handing its root the corpus
(`PlatformAgents`); their kinds and tools join the adopter's. The tools
that read a manager take it late, once the root has built it; the
engineer's pull request also takes the intake the process builds over
those managers, and with none it opens nothing. A station
daemon's report, through the gateway, finishes a validation session with
the id of the execution record its run wrote.
