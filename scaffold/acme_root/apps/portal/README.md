# Acme portal

The browser app a signed-in person uses: React, TypeScript, Vite, TanStack
Query, and Zustand. It holds the shell every product screen sits in:
sign-in, the left bar of sessions, the search over the whole app, the org
chip and switch, settings, and one realtime channel.

## The shell and the product's slot

A signed-in page sits beside the left bar. From the top: the org chip,
Search (⌘K), New session, Automations, Knowledge with its count of
suggestions to review, the product's entries, and the sessions grouped by
what they ask: Needs you, Running, and Recent, each sub-agent under its
parent. The user chip at the foot holds Settings, Profile, the theme, the
keyboard shortcuts, and Sign out. ⌘B folds the bar; its edge drags to resize.

What is set up once lives in Settings (`/settings`, ⌘,), out of the bar a
person scans every day. There, Settings' own bar takes the left bar's
place: back to the app, a search (`/`), and the sections by group.
Personal holds the profile; Organization its general facts, members,
usage, and audit; Agents the projects, models and keys, and playbooks;
Security the API keys and single sign-on; and a product adds its own. An
old address (`/projects`, `/models`, `/playbooks`, `/audit`, `/usage`)
lands on its section, and `/approvals` on the sessions that need you.

Every text field shows a realistic example of what goes in, and an ⓘ says
what a field means where its name does not. `watermarks.test.ts` holds
every platform screen to it.

A product adds its pages, left bar entries, session tabs, tool cards,
settings, agents, and examples in `src/product.tsx`, and edits no platform
file. The platform's own sit in `src/app/platform.tsx` in the same shape.
The shell joins the two and refuses an id or an address they share, so a
product never shadows a platform screen
([ADR 2042](../../docs/adr/2042-a-product-fills-the-portals-slot-and-never-shadows-a-platform-screen.md)).
Each route says what it shows in its `handle`: one line, and what each
parameter names. The route catalog lists them, and
[`docs/portal-routes.md`](../../docs/portal-routes.md) is its Markdown, in
the support assistant's corpus. Its test fails while a page says nothing
or the document differs; `vitest run -u src/app/routeCatalog.test.ts`
writes it again.

## Support

"?" beside the user chip, ⌘/, or "Ask support" in the search opens the
support dock: a conversation with the platform assistant at the right
edge, beside whatever page is open. ✕ or Esc closes it. The dock is the
shell's own column, so it never shares one with the page. When a session's
page is short of room, its pane folds to its icon rail first, and only then
does the dock narrow, never leaving the story under its minimum. Under 1100
pixels the dock is a sheet over the page, and Expand gives the chat the
page's width.

A link in a reply is a chip only when the router serves its address; it
opens that page in the main area and leaves the dock as it is. Any other
link shows as its words and its address. Each message carries the page the
person is on, as data. The dock keeps its draft and its conversation while
the person moves between pages, and continues a person's standing
conversation only when it is their own
([ADR 2045](../../docs/adr/2045-the-support-dock-continues-a-conversation-only-when-it-is-the-persons-own.md)).

## Layout

- `@acme/client`, from [clients/typescript/](../../clients/typescript/README.md):
  the one transport client and the types generated from the API's document.
  The portal calls `fetch` nowhere and never reads the generated schema.
- `src/app/`: routes, the slot (`product.ts`, `platform.tsx`), the query
  cache, the session, and the one client instance the app shares.
  `src/app/shell/` is the frame: the left bar, Settings' own bar, the
  search, and their keys.
- `src/features/<name>/`: one folder per screen, a pure model, a
  view-model hook, and a page. `home/` is the composer that starts a
  session on an agent and a project. `sessions/` is All sessions, with its
  filters; `session/` is
  one session's page: its thread, timeline, tools, evidence, changes, and
  children, live while it runs. The org's records and settings each have
  their own: `projects/`, `models/` (the org's own provider keys and its
  model for each role), `automations/`, `playbooks/`, `knowledge/`,
  `audit/`, `usage/`, and `settings/` (the overview, the profile, the
  org's general facts, members, API keys, and single sign-on).
  `providers/` is the banner a page shows while the org's sessions wait
  on a model provider. A secret field is write-only: the form sends it
  once, and the page shows only who set it and when. A new API key's
  secret shows once, until Done.
- `src/queries/`: query keys and hooks, one file per API namespace.
  `flags.ts` reads the session's flags as one snapshot from the API, and a
  view-model reads a flag with `useFlag`. No flag vendor's SDK is in the
  bundle.
- `src/realtime/`: the socket; a push invalidates the queries of its entity.
- `src/store/`, `src/design/`: client state and the design kit. The kit's
  views (a diff, a log, Markdown, JSON, a sortable table, a lightbox, a
  command palette, a tooltip, a popover, a pane's splitter) each keep their
  logic in a pure `*Model.ts` beside them. Its icons are Lucide's, drawn
  the kit's way by `kitIcon`. Markdown never becomes HTML.
- `e2e/`: the browser check, Playwright against a running stack.

## Run

```bash
pnpm --filter @acme/portal dev    # http://localhost:5173, /v1 goes to 127.0.0.1:8000
pnpm --filter @acme/portal test
make openapi                      # regenerates the client's types
```

On the local stack, `/login/dev` signs in by address alone.

The browser check needs the whole stack up: the API, the maintenance
worker, the session runner on the scripted provider, and this dev server.
It starts none of them. The session runner reads its script from
`ACME_MODEL_SCRIPT`, which `portal_check.py` writes, and a session's kind
is registered only when `ACME_CORPUS_ROOT` is set:

```bash
uv run --package acme-api python services/api/tests/portal_check.py script .local/model-script.json
# start the runner with ACME_MODEL_PROVIDERS=scripted, ACME_MODEL_SCRIPT,
# ACME_MODEL_SCRIPT_PACE_SECONDS=0.15, and ACME_CORPUS_ROOT set
ACME_PORTAL_URL=http://127.0.0.1:5173 pnpm --filter @acme/portal e2e
```

The script holds one turn, so the runner restarts before the check runs
again. The pace keeps the run open long enough to see it under Running.
The check signs in as the seeded owner, starts a session on Home, sees it
under Running and then Recent in the left bar, and reads its chat and, in
the panel, its evidence. It then signs in a person of another org, who
finds no row of it and nothing at its address. The records check needs
only the API, on the scripted providers, and this dev server: in Settings
the owner makes a project with a read credential, saves a provider key,
and creates an API key, and then makes an automation; each is read back
from the API. The credential's password and the provider key come back in
no reply and on no screen, and the API key shows once, then on no screen.
Their screenshots land in `e2e/screenshots/`, which git ignores.

The timeline check plays the engineer's scene: it thinks, plans, starts
two analysis sub-agents and waits for their reports, runs a failing test,
edits, runs it again, opens a pull request, asks its person, validates,
and submits its result. Its API and runner are `portal_stack.py`'s, which
register a scene engineer and analysis that work in a directory on this
host and clone the org's repository from a folder of bare ones; the forge
is its twin, seeded with it. The runner runs one loop at a time, since
one script answers every session, and a scene plays once per runner:

```bash
uv run --package acme-api python services/api/tests/portal_check.py script .local/scene.json --scene engineer
# with ACME_FORGE_INTEGRATION=twin and ACME_WORKSPACE_BACKEND=host set for
# the seed, both processes, and the check, and PORTAL_REPOSITORIES naming
# an empty folder:
uv run --package acme-api python services/api/tests/portal_stack.py api --port 8000
uv run --package acme-session-runner python services/api/tests/portal_stack.py runner
ACME_PORTAL_URL=http://127.0.0.1:5173 pnpm --filter @acme/portal e2e e2e/timeline.spec.ts
```

The check writes the scene's repository and its project's policy itself
(`portal_check.py scene`). It sees the first thought and words stream
before their step lands, pauses and resumes the session from its header,
approves each command it holds, answers its question, and opens a work
block and a diff. Each moment is shot light and dark.

The pane check plays the same scene on the same stack, with
`PORTAL_API_URL` naming the API:

```bash
PORTAL_API_URL=http://127.0.0.1:8000 ACME_PORTAL_URL=http://127.0.0.1:5173 pnpm --filter @acme/portal e2e e2e/pane.spec.ts
```

It sees Workspace open itself while the session runs and Changes once it
delivers, opens a step from a line of a work block, and opens the other
views from "+". It then takes control and runs `pytest -q`: the local
stack runs no host, so `portal_check.py host` stands in for the one that
holds the workspace, on a clone of the scene's repository at the
engineer's branch. It gives control back and reads the agent's reply,
hides and shows the pane, and reloads to find its tabs kept.

The sub-agents check runs on the same stack, with `ACME_CORPUS_ROOT` set
for the check too, since the tree it writes starts the scene's engineer,
and on a runner of its own, since it plays the scene:

```bash
ACME_PORTAL_URL=http://127.0.0.1:5173 pnpm --filter @acme/portal e2e e2e/subagents.spec.ts
```

The scene never has a sub-agent ask its person, so `portal_check.py tree`
first writes an engineer's tree through storage, within its bounds: one
answer that starts two sub-agents, a park on them, the first one's report,
and the second at work. The check reads the card that follows each child,
opens the report's child and comes back from its first card, and folds the
parent's row in the left bar. The tree's next beats park the second child
on its person, which raises a toast on the page open, then end it, which
settles the card. Then the check plays the scene: the engineer's answer
starts two analysis sub-agents, and the check follows each child's row
until it is done, reads each report, and finds the tree's bounds in the
Sub-agents tab: 2 of the 10 sub-agents it may start.
