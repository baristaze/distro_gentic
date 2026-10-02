# distro_gentic

A closed-loop, cloud-first, distributed agentic platform: a fleet of
agents for many tenants, unattended, on machines it does not always
own, where work arrives on its own, evidence goes out, and the world's
answer comes back into the same session.

The platform stands on two foundations and repeats neither. The
[Software Design and Architecture
Guidelines](https://github.com/baristaze/swe_guidelines), *the
guideline*, answer every question of general software design. The
engine, [`agentic_core`](https://github.com/baristaze/agentic_core),
runs one agent. This repository ships in the guideline's own shape: a
spec that tells the story, and tools that hold the detail.

- **[`distro_gentic_spec.md`](distro_gentic_spec.md)**: the spec. It
  says what the platform adds, what it guarantees, and why. Start with
  its [Core](distro_gentic_spec.md#the-core).
- **`lenses/`**: the checkable detail under each rule of the spec, one
  file per group, in the guideline's lens format.
- **`skills/`**: skills named `distro-*` that review a change through
  the lenses, explain a rule, record a deviation, and scaffold the
  platform's parts. They follow the [Agent
  Skills](https://agentskills.io/specification) standard.
- **`scaffold/`**: the platform's domain-free core, built on the
  engine's scaffold. A product renders it under its own name.

[The Repository](distro_gentic_spec.md#the-repository) in the spec says
what each part holds. A part's folder appears with the change that
builds it, and `make check` already holds the folder to its gate.

## How this repository is written

The spec and the READMEs have two readers, a person and an agent. They
tell the story: what each part is, and why. They point at the detail
rather than spell it out. Nuance that only an agent needs sits in a
short `<!-- agents-only -->` comment, which a rendered page hides. The
lenses and the skills are read by agents. They may be exact, and they
point at the scaffold's files rather than describe code.

The detail lives in the tools, and that is a choice. The spec tells the
story. The lenses and the skills hold the detail under each rule, and
they are stricter than the story on purpose. The gates are stricter
still. A tool may be stricter than the section it cites, and never
contrary to it.

## Install the skills

In Claude Code, the repository is a plugin marketplace:

```text
/plugin marketplace add baristaze/distro_gentic
/plugin install distro-gentic@distro-gentic
```

The full review, `distro-review-full`, judges all three layers: the
platform's rules itself, and the engine's and the guideline's through
their own full reviews. Install their plugins beside this one, or its
report names their layers as not run.

## Develop

```bash
make check       # everything CI runs
make gen-toc     # regenerate the spec's Contents from its headings
make gen-skills  # regenerate the review skills from the template and the lenses
```

[`CONTRIBUTING.md`](CONTRIBUTING.md) says what `make check` needs and
how a change lands. [`AGENTS.md`](AGENTS.md) holds the layout and the
writing rules.

## License

Apache 2.0. See [`LICENSE`](LICENSE).
