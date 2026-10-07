---
name: distro-upgrade-scaffold
description: "Move a product's base to a later platform release: a product rendered from the platform's scaffold, or a layer that takes its scaffold/ folder unchanged. Runs the guideline's arch-upgrade-scaffold with the platform as its source, so one move takes all three foundations, and adds what the platform's layer holds: its releases, its ADR numbers, its migrations and their stamps, and a layer's gates in a copy."
allowed-tools: Read, Grep, Glob, Edit, Write, Bash(curl:*), Bash(gh api:*), Bash(gh release view:*), Bash(python3:*), Bash(git status:*), Bash(git fetch:*), Bash(git rev-parse:*), Bash(git symbolic-ref:*), Bash(git switch:*), Bash(git log:*), Bash(git show:*), Bash(git diff:*), Bash(git merge:*), Bash(git merge-base:*), Bash(git checkout:*), Bash(git rm:*), Bash(git add:*), Bash(git commit:*), Bash(git ls-files:*), Bash(git ls-tree:*), Bash(grep:*), Bash(uv lock:*), Bash(pnpm install:*), Bash(docker info:*), Bash(lsof:*), Bash(make setup), Bash(make check), Bash(make openapi), Bash(make infra-up), Bash(make migrate), Bash(make migrate-check), Bash(make test-integration)
---

# distro-upgrade-scaffold

A path that starts with `../` is read from this skill's folder as
`realpath` resolves it.
Sections of `../../distro_gentic_spec.md`: The Repository.

A product's base is one render of the platform's scaffold, which holds
the engine's at the engine release the platform took, and through it
the guideline's at the release the engine pins. A product renders it at
its root, under its own name. A layer, a platform built on this one,
takes the platform's `scaffold/` folder unchanged. The guideline's
`arch-upgrade-scaffold` makes the move for both, with the platform as
its source, so one move takes all three foundations. This skill holds
only what the engine's layer and the platform's add.

## The procedure

`<pin>` is the guideline release this plugin's scaffold pins: `pinned
at release` in `../../scaffold/acme_root/specs/architecture.md`, which
already holds the `v` (`v0.52.1`). Read the guideline's skill at that
release,
`curl -fsSL https://raw.githubusercontent.com/baristaze/swe_guidelines/<pin>/skills/arch-upgrade-scaffold/SKILL.md`,
and follow it, with the differences below. Its `<base.py>` is the
absolute path of this plugin's `../../scaffold/base.py`, the same
script. Every other path it names from its own folder is the
guideline's file at `<pin>`, read from
`https://raw.githubusercontent.com/baristaze/swe_guidelines/<pin>/<path>`.

## Input

`[<ref>] [--name <name> | --layer] [--from <ref>] [--tarball <file>]`,
read as the guideline's skill reads them, with these differences.

- The source is the platform, `https://github.com/baristaze/distro_gentic`,
  and every run of `base.py` carries
  `--source https://github.com/baristaze/distro_gentic` among its
  `<flags>`: a product's render is
  `python3 <base.py> <ref> --name <name> --source https://github.com/baristaze/distro_gentic`,
  and a layer's is
  `python3 <base.py> <ref> --layer --source https://github.com/baristaze/distro_gentic`.
  `base.py` refuses a `--source` other than the one the base records,
  so a base that holds the engine or the guideline is not this skill's:
  stop and say so. The repository is private: `base.py` reads it with
  the token `gh auth token` gives, and `--tarball` serves a machine with
  none.
- `<ref>` is a release tag of the platform, never of the engine or the
  guideline, whose releases the platform's base and pin name. Without
  one, it is the release after the one the base records. The platform's
  releases and their commits:
  `gh api --paginate repos/baristaze/distro_gentic/tags --jq '.[] | "\(.commit.sha) \(.name)"'`,
  read in version order, so `v0.10.0` follows `v0.9.0`. The base's
  release is the tag whose commit is its `Scaffold-Commit`, and the
  target is the next. A move takes one platform release: when releases
  lie between the base's and a target named, the target is the first of
  them. When the base's commit is no release, `<ref>` is required. When
  no release is above the base's, stop: there is nothing newer. A
  layer's first take has no base, and without `<ref>` takes the newest
  platform release in that listing.
- `--from <ref>`: the platform release a checkout with no base was
  copied from. A copy that `../../scaffold/new.py` made from a clean
  checkout of a release records its base, and needs none.

## What the platform's layer adds

- **The graft** (its step 3). A checkout with no base grafts at the
  platform release it was copied from, never at its pin:
  `python3 <base.py> <from> <flags>`, then the merge that changes no
  file, as that step gives it. Without `--from`, stop and ask for it. A
  layer's first take grafts nothing, as there.
- **What the releases ask** (its step 5). The platform's notes at the
  target:
  `gh api -H 'Accept: application/vnd.github.raw' 'repos/baristaze/distro_gentic/contents/CHANGELOG.md?ref=<ref>'`.
  When the target takes a later engine release than the checkout's
  base, also read the engine's notes up to it,
  `gh api -H 'Accept: application/vnd.github.raw' 'repos/baristaze/agentic_core/contents/CHANGELOG.md?ref=<engine ref>'`.
  When it pins a later guideline release (`pinned at release` in
  `<root>/specs/architecture.md`, before and after the merge), also read
  the notes of each guideline release above the checkout's pin up to
  the target's, `gh release view v<X.Y.Z> --repo baristaze/swe_guidelines`.
  One move takes all three foundations, and a deviation the checkout
  records may be one a release now holds.
- **ADR numbers** (its step 6, `docs/adr/`). The base's records come in
  as the scaffold's: the guideline's below 1000, the engine's from 1001
  to 1999, and the platform's from 2001 to 2999. The checkout's own sit
  in the thousand above: from 3001 on the platform, and in the thousand
  above a layer's own on a layer built on it. A scaffold ADR never takes
  a number in the checkout's thousand, and the checkout's never one in
  the scaffold's.
- **Migrations and their stamps** (its step 6). The platform's
  migrations sit in the guideline's four role chains, after the
  engine's, which sit after the guideline's, and all three are the
  scaffold's. A role's scaffold head is the render's: the platform's
  last migration of that role where it has one, else the engine's, else
  the guideline's. A migration's stamp is its `revision`, and its parent
  is its `down_revision`. The checkout's own migrations keep their
  stamps in a copy, which applies databases: what a database applied is
  never renamed. In a layer, which applies none, the scaffold's gate
  holds each role's head to its highest stamp, so the first of a role's
  own chain is re-pointed to the new scaffold head and the chain takes
  stamps above that head, in order, each parent following. Where the
  guideline's table re-points the first of a role's own chain in a
  copy, only its `down_revision` changes. A migration the checkout writes
  for a scaffold change takes a stamp above every stamp of its role,
  the scaffold's included, and its role's head as its parent. After the
  merge, each role has one head:
  `grep -rn "^down_revision" <root>/om/migrations/versions/<role>/`
  names every parent once, and the gates' `make migrate` applies each
  chain from empty.
- **A layer's gates** (its step 8). A layer runs its scaffold's gates in
  a copy, as the platform's CI does, never in `<root>`. From the
  checkout's root, `python3 scaffold/new.py <dir>/<name>` copies it into
  a folder outside the checkout. In the copy, `make setup` and
  `make check`; when `docker info` exits 0, `.env.example` copied whole
  to `.env`, each port in it that `lsof -i :<port>` finds taken moved to
  a free one, then `make infra-up`, `make migrate`, `make migrate-check`,
  and `make test-integration`. `make openapi`, when its step asks for
  it, still runs in `<root>`, where what it writes is committed. The
  layer's own gates, as its `AGENTS.md` names them, run at its root. A
  fix goes into the checkout, never the copy, and a fresh copy runs the
  gates again.
- **The merge into the main branch.** The move's commits sit on the work
  branch, and the render sits on `scaffold`. The pull request that
  carries them merges with a merge commit, never a squash: the merge
  commit is what records the base, and a squash drops the parent the
  next move merges against. Nothing deletes, rebases, or force-pushes
  `scaffold`; each commit there is one render, with the render before as
  its parent.

## Output

As the guideline's skill gives it, with the platform release of the
base before and after, the engine release and the guideline release
each takes, and each migration whose parent the move re-pointed, with
its stamp and both parents.
