# A tree of sub-agents

![The portal running a tree of sub-agents: a person asks the software engineer to read every date day first; its answer starts four sub-agents, each a row on a card in its chat and nested under its row in the left bar; one asks the person, who answers in its chat; one starts a sub-agent of its own; each row closes as its sub-agent reports; the lead writes the roll-up, the person approves the commit, folds the tree, and approves the validation, and the lead submits its result](tree.gif)

The portal of a copy of the scaffold, running a tree of sessions on
its local stack. The session runner answers from a script on the
scripted provider, so it reads no key, sends nothing to a model
provider, and bills nothing. Every row, status, card, and report in
the frames is what the stack wrote: its API, its runner, and its
maintenance worker. The recorder acts as a person does: it types,
clicks, and reads.

## What it shows

One task, run by a lead and the sub-agents it starts.

1. **The ask.** On Home, the person asks the software engineer to read
   every date in the app day first. Its one answer takes a baseline,
   starts four analysis sub-agents, and waits on them.
2. **The tree at work.** Each sub-agent runs in a session of its own.
   The first reads the parser and reports. The second searches for the
   parser's callers and asks its person a question. The third starts a
   sub-agent of its own to read the test, which reports to it, and then
   reports itself. The fourth reads the invoice and reports.
3. **The person.** The one that asks needs its person, and a toast says
   so. The person opens it and answers in its chat; it reports, and its
   row closes.
4. **The roll-up.** Woken by the last report, the lead writes what its
   sub-agents found and fixes the parser. It holds its commit for the
   person's approval, and the person folds the tree under its row in the
   left bar. It opens a pull request, holds its validation for approval
   too, validates its head, and submits its result.

## How to read it

- **The left bar** lists the person's sessions. The lead's row holds its
  sub-agents nested beneath it, and a sub-agent's own beneath that
  one. Each row says where its session stands. Folded, the lead's row
  counts its sub-agents.
- **The card** in the lead's chat, *Started 4 sub-agents*, holds a row
  for each sub-agent. Each row follows its session live: starting,
  working, needs you, done.
- **A report** is each sub-agent's last answer, as its parent reads it.
- **The toast** names a sub-agent that needs its person, and opens it.
- **Action required** is a call the lead holds until the person
  approves it.
- **The result** is the lead's claim, judged against the runs it cites.

## Run it

The recorder drives a copy of the scaffold with its stack up. It needs
ffmpeg, and Playwright's Chromium, which
`uv run --no-project --with playwright==<pin> playwright install chromium`
installs once. From the repository's root:

```bash
python3 scaffold/new.py ../distro && cd ../distro && make setup
cp .env.example .env
# in .env: SEED_EMAIL=demo@example.com, DISTRO_FORGE_INTEGRATION=twin,
# and DISTRO_AGENT_WORKSPACE_BACKEND=host
make infra-up migrate seed
cd - && make demo-gif DEMO_COPY=../distro
```

`make demo-gif` starts the rest on the copy and stops it when it ends:
the API and the session runner as the copy's `portal_stack.py` starts
them, on the scene's script, the maintenance worker, and the portal's
dev server on `DEMO_PORTAL_PORT`. It writes the scene's repository on
disk, and the copy's `portal_check.py scene` writes the validation
policy of the agent project that binds it. The scene plays once on a
seed: an org that holds a session already is refused, and
`make infra-reset migrate seed` in the copy makes a fresh one.

It plays as the seeded owner, at `example.com`, and refuses any other
address, so no frame shows a real one. Every request the page makes
must stay on the portal's origin, which forwards the API. A page error,
a console error, a request off the origin, or a GIF of 6 MB or more
fails the recording, and the GIF is written only when none happened.
It prints the time of each beat in the GIF. CI does not run it.

## Where things are

- [`scene.py`](scene.py): the words. The person's prompt and answer,
  the repository the lead works on, and every turn of the script, in
  the order the runner asks for them.
- [`stack.py`](stack.py): the copy, its settings, and the processes the
  scene runs on.
- [`record.py`](record.py): the drive, as the person plays it, and its
  guards.
- [`film.py`](film.py): the frames as the run goes, and the GIF made of
  them: faster where the screen changes, short where it stands still,
  and a pause on each beat. The person setting out their view, the left
  bar's width and the session's pane, is cut.

It sits outside the scaffold, so no copy of the scaffold carries it.
