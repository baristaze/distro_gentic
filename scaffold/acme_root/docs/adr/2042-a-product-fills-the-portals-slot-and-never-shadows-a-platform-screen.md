# ADR 2042: A product fills the portal's slot and never shadows a platform screen

**Status**: accepted (2026-10-05)

## Context

The portal is the screen a person starts, watches, and steers sessions
from. A product built on the platform adds screens of its own: a page
for its own records, an entry in the left bar, a tab in a session, a
card for one of its tools, a section of Settings, an agent of its own,
and the examples its fields show. With no hook for these, it edits the
platform's routes, its left bar, and its session page, and every base
move fights those edits.

The server side already answers this for kinds
([ADR 2025](2025-a-product-adds-its-own-kinds-through-the-registries-the-platforms-go-through.md)):
a product hands its kinds to one registry the platform's own go
through, and a name held twice is refused at boot.

## Decision

**The portal has one slot, and the platform's own entries fill it the
same way.** `src/app/product.ts` names its shape: routes, left bar
entries, session tabs, tool views, settings sections, agents, and
examples. The platform's entries sit in `src/app/platform.tsx`. A
product fills `src/product.tsx`, which the base ships empty, and edits
no other file of the portal.

**The shell joins the two once, at start, and refuses what they share.**
`joinProducts` throws a `SlotConflict` on an address two routes serve
(a parameter counts by its place, not its name), and on a left bar
entry, a session tab, a tool, a settings section, or an agent kind
named twice. The app stops before anything renders, so a product never
shadows a platform screen in silence.

**The order is the platform's, but for the agents and the examples.**
Routes, left bar entries, tabs, and settings list the platform's first.
The product's agents come first, so its first is the composer's
default, and its examples replace the platform's where it gives them.

**A screen reads the joined slot from the shell**, through a React
context, never by importing the product. A test hands a screen the slot
it needs, and no page imports the module that imports it.

## Consequences

- There is no route that lists agent kinds, so the slot names them. A
  kind the slot does not name can still run; it is not offered on Home.
- A left bar entry's count is a hook, called on every render of its
  entry, so it reads through the query cache like any screen.
- The settings sections are entries of the slot with their own routes,
  so a product's section sits beside the platform's, and the search
  finds both.
- A product that needs a platform screen to change still changes the
  platform. The slot holds what a product adds, not what it replaces.
