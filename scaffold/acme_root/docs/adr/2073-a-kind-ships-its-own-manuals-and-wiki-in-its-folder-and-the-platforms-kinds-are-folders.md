# ADR 2073: A kind ships its own manuals and wiki in its folder, and the platform's kinds are folders

**Status**: accepted (2026-11-21)

## Context

The engine keeps a kind in a folder of its own: a module of typed
versions, and each version's prompt in Markdown, pinned by its digest
([ADR 1046](1046-a-kind-is-a-folder-its-prompts-are-markdown-pinned-by-digest-and-it-names-who-starts-it.md)).
The platform's six kinds were still one module of constants, with each
prompt a run of string literals and the layers of a version a tuple of
them. A person who read or changed one read Python to do it.

A kind's texts were its prompts alone. Every other text its sessions
read came from the tenant: the kind manual it pins
([ADR 2056](2056-an-agent-playbook-is-invoked-by-a-person-or-an-agent-automation-and-pinned-to-a-kind-as-its-kind-manual.md))
and the agent knowledge it reviews. A kind had no place for an
operation manual of its own, or for what every session of it should
not rediscover, without making it a tenant's row that the tenant may
edit, reject, or erase.

## Decision

**The platform's kinds are folders.** Each sits in
`platform_agents/kinds/<kind>/`: `kind.py` holds its versions, typed,
and `VERSIONS`, and `prompts/v<N>.md` the prompt of each version, pinned
in `prompts/lock.json`. Each file holds its version's prompts as the
literals held them, joined by a blank line. Each version keeps every
setting, and states who may start it. What the kinds share, their
names, their tools, and their toolsets, stays in the `kinds` package.
`shipped.py` reads each folder, and `SHIPPED` is their versions.

**A folder ships the kind's own texts beside its prompts.**
`manuals/<name>.md` holds an operation manual, rendered whole.
`wiki/<slug>.md` holds a knowledge entry: a header of its title and
the words that trigger it, then its text. `folder_of` reads them with
the versions, and a text that cannot be read, a malformed one, or
manuals past a third of the standing text's bound together refuse the
folder.

**A kind's manuals open each new session's standing text.** The root
puts a layer beneath every agents layer it is given, so every way a
session is made takes them: a start, a spawn, and a hand-off. The
kind's manuals come first, then the kind manual the tenant pinned,
then any text the maker sent, all within the standing text's bound. A
pin that would not fit after the kind's manuals is refused as it is
pinned. A switch of the standing text is a person's act, and replaces
the manuals with the rest, as it replaces a kind manual.

**A kind's wiki is agent knowledge of the kind's own.** A session of
the kind recalls an entry its subject triggers, as data, before the
tenant's. Its agent finds the entries with `search_agent_knowledge`,
under the scope `kind`, and reads one by its handle, `<kind>/<slug>`,
which no tenant's slug can take. A session of another kind never
reaches them.

**Both stay the kind's.** No tenant's row holds them, so no tenant
edits, rejects, or erases them, and no recall of an entry is kept,
since no tenant's lever reading should rank it. They are reviewed as
the kind's code is.

**A product's kinds are folders the same way.** It keeps them in its
own folder of kinds, beside the platform's, and declares each one with
`ProductKinds.folders`, from `folder_of`. A kind it declares as two
folders, or as a folder and alone, is refused.

**A check holds every folder.** `folder_breaches` runs the engine's
`prompt_breaches`, then the platform's own: a file that is no
`<name>.md`, a text not UTF-8, empty, or past its bound, an entry whose
header is not its title and its trigger, and every finding the lever
checks make
([ADR 2054](2054-a-lever-is-checked-as-a-person-publishes-it-and-read-back-from-the-sessions-that-stalled.md)).
A finding advises a tenant, and fails the gate of a kind's own text.
The scaffold's tests run it over the platform's folders and the
product's, and hold every product folder declared.

## Consequences

- A version that composed several prompts renders them as one block.
  Its text is the same, and its sessions write their cached prefix
  once more.
- The test that pins each current version's request pins its tools,
  and the lock pins its prompt, so each holds one pin.
- Each released version's settings are pinned by digest in the
  scaffold's tests, as its prompt is in its lock.
- The platform's kinds ship no manuals and no wiki yet. A root wraps
  its agents only when a kind ships manuals.
