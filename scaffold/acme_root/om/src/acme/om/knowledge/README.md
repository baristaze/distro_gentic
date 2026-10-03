# Knowledge

What a new session should not have to rediscover about its environment.
This is one of the kinds of thing [Acme is made
of](../../../../README.md).

## What it holds

- **Entry**: a title, the words that trigger it, and what it says, with
  its state: suggested by an agent, reviewed by a person, or rejected.

## What can happen

- **Suggest.** An agent suggests an entry from its session.
- **Write.** A person writes an entry in person; it is reviewed as it is
  written.
- **Review.** A person keeps or rejects a suggestion, in person.
- **Read.** The tenant's entries in a state, the suggestions waiting on
  a review among them, and one entry.
- **Edit.** A person edits an entry in person, on the version they read.
  A reviewed entry's words are then the editor's, so the editor is its
  reviewer; a suggestion still waits for its review, and a rejected one
  is written again instead.
- **Recall.** The reviewed entries whose every trigger word appears in
  what a session is about arrive in it, once each, at its next model
  call. A session recalls as it starts: when its first loop prepares the
  workspace, its title and what its principals said so far are what it
  is about, and its first model call reads what they trigger.

## The rules

- **Nothing unreviewed is recalled.** A suggestion waits for a person,
  so one session cannot plant instructions for the next.
- **Recalled knowledge is data.** It arrives as an event the agent reads
  quoted, whoever wrote it.
- **A session does not rediscover its environment.** What its subject
  triggers is there before its first model call.
- **Every row belongs to one org,** and goes with the org.

<!-- agents-only
The recall at start is the tools layer `root.KnowledgeLayer`, around
`prepare_workspace`, for a session with no model request yet
(`AgentSession.speaker` is None). A root that runs loops wraps its tools
in it.
-->
