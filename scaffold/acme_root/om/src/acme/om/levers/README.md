# Levers

The texts a tenant customizes its agents with, read for what misleads or
stalls an agent. This is one of the kinds of thing [Acme is made
of](../../../../README.md).

A lever is a [playbook](../playbooks/README.md) or a reviewed
[knowledge](../knowledge/README.md) entry: words written for people
that an agent then reads and follows. A phrase repeated until it looks
load-bearing, a must and a must-not on one subject, a tool no kind
holds, or "keep trying until it works" makes an agent spin. The levers
are read twice: before a person publishes one, and after, against the
sessions that stalled.

## What it holds

- **A finding**: what a check read in a lever's text, kept with the
  version it read, by the swimlane that keeps the lever.
- **A reading**: one tenant's sessions over a window, each with its
  stall, read from its steps' headers, and the levers it reached; and
  the levers ranked by how much more often the sessions that reached
  them stalled.

It keeps no table of its own.

## The checks

Each runs on the text alone, calls no model, and runs nothing it reads.
They find:

- a phrase of three to six words said past a bound that grows with the
  text;
- a must and a must-not on one subject;
- a tool or a kind it names that no kind it reaches holds, a playbook's
  gates included;
- an instruction to retry with no stopping condition;
- a playbook longer than a session holds whole once it summarizes.

A lever reaches every kind its tenant's sessions start on, at its latest
version.

## The rules

- **A finding advises, never refuses.** A publish or a review lands
  whatever the checks find, and answers the findings beside it.
- **A finding is kept with the version it read.** A new version is read
  again.
- **A reading reads headers.** A session's stall is what its steps'
  headers say: a call made again and again, a call failing again and
  again, a request sent again unchanged, a nudge, a guard, a loop a bound
  ended. It never opens what a step says.
- **A reading names its levers and its sessions.** A lever every session
  reached ranks nowhere, and so does one no more often present where
  sessions stalled.
- **Only an operator reads it,** under `read`, and the read is logged
  with the tenant and the operator.

## How another namespace composes it

The playbooks and the knowledge swimlanes run the checks as a person
publishes, writes, edits, or keeps an entry, against `reach_of` their
root's kinds. The knowledge swimlane records the version each session
recalls, as the playbooks swimlane records each invocation, and the
reading reads both.
