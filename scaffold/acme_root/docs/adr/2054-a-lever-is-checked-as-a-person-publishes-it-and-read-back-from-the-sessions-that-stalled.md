# ADR 2054: A lever is checked as a person publishes it, and read back from the sessions that stalled

**Status**: accepted (2026-10-11)

## Context

A tenant customizes its agents with texts its people write: an agent
playbook, which a principal invokes into a session, and a reviewed agent
knowledge entry, which a session recalls. These are its levers. A lever
is written for people, and an agent reads it differently. A phrase said
again and again reads as the one that matters. A must and a must-not on
one subject leave it going back and forth. A tool no kind holds sends it
looking. "Keep trying until it works" makes it repeat a call. The
engine already ends a loop that stalls: a run of identical calls, a run
of failures, a turn with no call, a guard. Nothing tied a stall to the
lever before it, and nothing read a lever before it shipped.

## Decision

**A lever is checked as a person publishes it, and a finding advises.**
The checks are pure rules (`levers/rules.py`). They call no model, so a
publish spends nothing, and they run nothing they read. They read the
words a person wrote: an agent playbook's description and steps, never
the frontmatter and gates the platform writes around them, and an
entry's title and text. They find a
phrase of three to six words said past a bound that grows with the
text; a must and a must-not on one subject; a tool or a kind the text
names in backticks beside a word that calls it one, or an agent
playbook's gate names, that no kind it reaches holds; an instruction to
retry, or not to stop, with no stopping condition; and an agent playbook
whose brief, as a session receives it, is longer than the characters a
session's pinned zone holds whole. A quoted word, such as an environment
variable or a configuration key, is never taken for a tool, and an
instruction not to stop something is never taken for one not to stop. A lever
reaches the latest version of every kind its tenant's sessions start
on, which the root's managers now carry as `kinds`. An agent playbook is
checked as it is published, and an agent knowledge entry as a person
writes, edits, or keeps it. The publish lands whatever the checks find.

**A finding is kept with the version it read.** An agent playbook
version and an agent knowledge entry each carry their findings in their
own row, and the API answers them beside the publish or the review. The
portal shows them on the agent playbook and the entry. A version the
checks never read, one published before they ran, carries none: the API
answers `null` and the portal says it was not checked, never that the
checks found nothing.

**A stall is read back to the lever before it.** The operator plane
reads one tenant's sessions created in a window, newest first, within a
bound. A session's stall is read from its steps' headers alone, never
from what a step says, as the engine's limits read it: a call made a
third time running, a call failing a third time running, a request sent
again unchanged after its answer, a nudge, a guard, and a loop a bound
ended without a conclusion. Its levers are the agent playbook versions
it invoked and the agent knowledge versions it recalled or an agent read
by its slug; a recall and a read are now recorded, as an invocation
already was. Each lever ranks by how much more often the sessions that
reached it stalled than those that did not, and names the sessions
behind its figure. The reading answers a lever by its kind, id, and
version alone: its name or its slug is the tenant's words, and an
operator who reads sees shape, never content. A lever every session
reached has nothing to stand against, and ranks nowhere.
`audit-agent-levers` reads it through `acme-ops levers`.

**The levers keep no table.** A finding lives in its lever's row, and a
reading reads the sessions and what they reached. The namespace is the
checks, the reading, and their types, so the guideline's rule that
every namespace keeps storage takes an exception here, as the watch's
does.

## Consequences

- One migration: a `findings` column on `core.agent_playbooks` and
  `core.agent_knowledge_entries`, null for every row written before,
  which reads as not checked, and the table
  `core.agent_knowledge_recalls`, one row an entry in a session.
- A check is a heuristic. It is a net for what a person would want to
  read again, and it misses what it does not look for.
- A reading is bounded by the sessions and the steps it reads, and says
  when the window held more.
- A connector's tool descriptions join the levers once connectors
  exist: the checks read any text against a reach, and a reading takes
  any lever a session reached.
