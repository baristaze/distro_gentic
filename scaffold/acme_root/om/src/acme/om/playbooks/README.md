# Playbooks

A team's procedures as versioned, executable briefs. This is one of the
kinds of thing [Acme is made of](../../../../README.md).

## What it holds

- **Playbook**: one version of a brief in the [Agent
  Skills](https://agentskills.io/specification) format: its name, its
  description, its body (what is needed, the steps, the safety
  requirements, the success measures, what is forbidden), and its
  approval gates, which travel in a namespaced metadata extension.
- **Invocation**: a version a principal brought into one session.

## What can happen

- **Publish** the next version of a name, by a person in person.
- **Invoke** a version in a session, by a principal in person who may
  instruct it. Its brief arrives as that principal's message, and its
  gates hold there from then on.

## The rules

- **Only a person publishes,** and only a principal invokes. An agent's
  call does neither.
- **A gate only narrows.** A gate denies a call or holds it for a
  person's approval; none allows. A call the policy beneath refuses or
  holds stays so.
- **A version is written once.** A change is the next version.
- **Every row belongs to one org,** and goes with the org.

## How another namespace composes it

A root wraps its tools manager in the playbooks layer, so every call of
a session passes its playbooks' gates after the policy beneath it.
