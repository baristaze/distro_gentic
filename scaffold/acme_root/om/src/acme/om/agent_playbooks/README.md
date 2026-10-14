# Agent playbooks

A team's procedures as versioned, executable briefs. This is one of the
kinds of thing [Acme is made of](../../../../README.md).

## What it holds

- **Agent playbook**: one version of a brief in the [Agent
  Skills](https://agentskills.io/specification) format: its name, its
  description, its body (what is needed, the steps, the safety
  requirements, the success measures, what is forbidden), its approval
  gates, which travel in a namespaced metadata extension, and what the
  [lever checks](../levers/README.md) found in it as it was published.
- **Invocation**: a version brought into one session: by a principal,
  or the kind manual the session was made with, marked pinned.
- **Pin**: a version a tenant set as a kind manual, for the tenant's
  sessions of the kind or for one agent project's.

## What can happen

- **Publish** the next version of a name, by a person in person. The
  checks read it first, and what they find is kept with the version and
  answered beside the publish; a finding never refuses one.
- **Invoke** a version in a session, by a principal in person who may
  instruct it. Its brief arrives as that principal's message, and its
  gates hold there, and in every sub-agent below it, from then on, a
  session between them marked deleted or not.
- **Invoke** a version as an agent automation's start runs, under the
  context it runs as, into the session it started. The person who saved
  the agent automation chose the agent playbook then, as they wrote its
  brief.
- **Pin** a name's latest version to a kind as its kind manual, and take
  it away, by a person in person who manages the tenant. A pin for an
  agent project wins over the tenant's.
- **Make a session with its kind manual.** A start, a spawn, or a
  hand-off of a session not yet made records its kind's pinned version
  as the session's pinned invocation, then sends the version's brief as
  the session's standing text: its gates hold from the first call, and
  its text renders whole in the system layer of every request. A session
  that stands already keeps the kind manual it was made with.

## The rules

- **Only a person publishes,** and only a principal or an agent
  automation invokes. Only a person who manages the tenant pins. An
  agent's call does none of them.
- **A kind manual is whole and fixed.** A brief past what a session's
  standing text holds is refused when it is pinned, and a session never
  takes a kind manual after it is made.
- **A gate only narrows.** A gate denies a call or holds it for a
  person's approval; none allows. A call the policy beneath refuses or
  holds stays so.
- **A version is written once.** A change is the next version.
- **Every row belongs to one org,** and goes with the org.

## How another namespace composes it

A root wraps its tools manager in the agent playbooks layer, so every
call of a session passes, after the policy beneath it, the gates of the
agent playbooks it and each session above it invoked. Where a session of
that chain cannot be read, its gates are unknown, and the call waits for
a person. A root that makes sessions also wraps its agents manager in
the layer, so each session it makes takes its kind manual. An agent
automation reaches the manager through its root, to invoke the agent
playbook a start names.
