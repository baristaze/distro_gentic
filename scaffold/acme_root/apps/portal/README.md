# Acme portal

The browser app a signed-in person uses: React, TypeScript, Vite, TanStack
Query, and Zustand. It holds the shell every product screen sits in:
sign-in, the org chip and switch, settings, and one realtime channel.

## Layout

- `@acme/client`, from [clients/typescript/](../../clients/typescript/README.md):
  the one transport client and the types generated from the API's document.
  The portal calls `fetch` nowhere and never reads the generated schema.
- `src/app/`: routes, the nav, the query cache, the session, and the one
  client instance the app shares.
- `src/features/<name>/`: one folder per screen, a pure model, a
  view-model hook, and a page. `home/` is where the product's screens start.
  `sessions/` lists the org's agent sessions and starts one; `session/` is
  one session's page: its thread, timeline, tools, evidence, changes, and
  children, live while it runs.
- `src/queries/`: query keys and hooks, one file per API namespace.
- `src/realtime/`: the socket; a push invalidates the queries of its entity.
- `src/store/`, `src/design/`: client state and the design kit. The kit's
  views (a diff, a log, Markdown, JSON, a sortable table, a lightbox, a
  command palette) each keep their logic in a pure `*Model.ts` beside them.
  Markdown never becomes HTML.
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
# start the runner with ACME_MODEL_PROVIDERS=scripted, ACME_MODEL_SCRIPT and ACME_CORPUS_ROOT set
ACME_PORTAL_URL=http://127.0.0.1:5173 pnpm --filter @acme/portal e2e
```

The script holds one turn, so the runner restarts before the check runs
again. The check signs in as the seeded owner, starts a session, and reads
its thread, timeline, and evidence. It then signs in a person of another
org, who finds none of it. Its screenshots land in `e2e/screenshots/`,
which git ignores.
