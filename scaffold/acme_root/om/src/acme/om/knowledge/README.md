# Knowledge

What a new session should not have to rediscover about its environment.
This is one of the kinds of thing [Acme is made
of](../../../../README.md).

## What it holds

- **Entry**: a title, the words that trigger it, and what it says, with
  its state: suggested by an agent, reviewed by a person, or rejected. It
  belongs to one project of its tenant, or to the whole tenant, and
  carries a slug, its title's words and the end of its id, that an agent
  reads it by.

## What can happen

- **Suggest.** An agent suggests an entry from its session, for the
  session's project, or for the whole tenant when the session has none.
- **Write.** A person writes an entry in person, for the whole tenant; it
  is reviewed as it is written.
- **Review.** A person keeps or rejects a suggestion, in person.
- **Recall.** The reviewed entries whose every trigger word appears in
  what a session is about arrive in it, once each, at its next model
  call. A session recalls as it starts: when its first loop prepares the
  workspace, its title and what its principals said so far are what it
  is about, and its first model call reads what they trigger.
- **Search and read.** An agent searches the entries its session reaches
  by the words they share with a query, and reads one by its slug, when
  it needs to (the [agents' tools](../platform_agents/README.md)).

## The rules

- **Nothing unreviewed is recalled or read.** A suggestion waits for a
  person, so one session cannot plant instructions for the next.
- **A session reaches its project's entries and its tenant's alone.** An
  entry of another project, or of another tenant, is never recalled,
  found, or read, as one that never existed is not.
- **Recalled knowledge is data.** It arrives as an event the agent reads
  quoted, whoever wrote it.
- **A session does not rediscover its environment.** What its subject
  triggers is there before its first model call.
- **Every row belongs to one org,** and goes with the org.

<!-- agents-only
The recall at start is the tools layer `root.KnowledgeLayer`, around
`prepare_workspace`, for a session with no model request yet
(`AgentSession.speaker` is None). A root that runs loops wraps its tools
in it, and hands `KnowledgeLayer.manager` to `build_managers` as
`knowledge`, for the agents' tools. A session's project is read from the
projects' rows (`SessionProjectsInterface`), never from a call's input;
storage bounds every read to it (`read_reachable`, `read_by_slug`), and
the manager checks it again (`rules.reaches`).
-->
