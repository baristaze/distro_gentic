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
  files, searches the code, changes a file one place at a time or writes
  it whole, and runs commands. It searches and reads the
  [knowledge](../knowledge/README.md) its session reaches, and suggests
  an entry for a person to review. It opens its pull request on its
  own branch, which puts its committed head on the repository, asks for a
  validation of that head on a fresh executor, and submits its result
  through the
  [result gate](../evidence/README.md), citing the runs that validation
  wrote. A success counts only when the validation at its head passed.
- **Analysis** reads what a run produced (its logs, telemetry, and
  recordings) in a workspace of its own, searches it and the knowledge
  its session reaches, changes nothing, and answers with its findings.
- **A kind's versions**: a session keeps the version of its kind it
  started on, so the engineer and analysis before they searched and
  edited by one place are still shipped beside them.
- **The planner** turns findings into tasks. It reads where sessions
  stand, hands new engineering work to an engineer, and answers with its
  plan: each task and the session it goes to.
- **The platform assistant** helps the people who set up and run their
  part of the platform, on their own permissions. It explains the
  product from its corpus and cites it, diagnoses where a session stands
  by reading it, drafts the tenant's tool policy and shows the difference
  from what is live, and hands engineering work to an engineer. It has no
  workspace, repository, or shell.
- **The corpus**: what the [knowledge map](../../../../../llms.txt) lists
  for the tenant's users, read once when the process starts. A document
  listed only for the platform's own people is not in it.
- **A validation session**: one check of a project's policy, run on a
  fresh executor with no agent. It holds the project, the check, the
  delivered commit it runs at, and the base its checks, fixtures, and
  runner come from, and, once its run is recorded, which run it was.

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
- **Edit a file.** The engineer's `edit_file` replaces one place: a
  text that matches exactly one place in the file, or a range of its
  lines. A match of more than one place is refused, so an edit never
  lands where the model did not mean, and so is a file past the bound one
  read takes, or one that is not text. A path the session's project
  protects is refused at the call, as `write_file` refuses it.
- **Search the code.** `search_code` runs the workspace's own search,
  through the transport, wherever the workspace runs, never in the
  platform's process. Its answer is bounded in matches, in each match's
  width, and in the output it reads, and says whether more were left
  out. Its path is one inside the workspace.
- **Search and read knowledge.** `search_knowledge` answers the reviewed
  entries the session reaches and the passages of the corpus that share
  the most of a query's words; `read_knowledge` reads one whole by its
  slug, a corpus document by its path. `suggest_knowledge` suggests an
  entry for the session's project, which waits for a person's review.
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
- **Start a validation session.** A member who may write asks for a
  check at a delivered commit, with its checks from a base, as a CI job
  asks through the API. A check its project's policy does not declare is
  refused before anything is written, and so is a project whose policy
  is another tenant's. Its `VALIDATION` work goes on the platform's own
  lane of the [work queue](../work/README.md) in the same write, and the
  platform's worker claims it.
- **Run it.** The worker runs the check through the
  [evidence](../evidence/README.md) on a fresh executor: an instance
  nobody used, holding the delivered commit with the protected paths
  from its base, destroyed after the run. The run is recorded as an
  execution record, the record every run is, and finishing the session
  names it. A session runs its check once: asked again after its run
  was kept, it finishes with that run and runs nothing. Its verdict is
  that run's: it passed when the run passed and one of its cases did.
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
  2024](../../../../../docs/adr/2024-a-validation-session-is-platform-work-on-the-fresh-executor.md)).
- **A validation session never runs where an agent worked.** Its tree
  is read from the project's repository by the platform, and its
  protected paths come from its base, whatever the delivered commit
  holds there.
- **Nothing routes.** A person chooses an agent by choosing the session
  they type in.
- **Every validation session belongs to one org.**

## How another namespace composes it

A process ships these agents by handing its root the corpus
(`PlatformAgents`); their kinds and tools join the adopter's. The tools
that read a manager take it late, once the root has built it; the
engineer's pull request also takes the intake the process builds over
those managers, and with none it opens nothing. The maintenance
worker's `VALIDATION` handler runs a validation session
(`run_validation`); the evidence the root builds over the platform's
executor runs its check and keeps its execution record.
