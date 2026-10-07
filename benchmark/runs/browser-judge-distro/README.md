# browser-judge-distro

The subject is this repository, whole, at its public URL,
`https://github.com/baristaze/distro_gentic`, which the prompt names.
Four chat products a reader would use are asked about it: chatgpt.com,
claude.ai, gemini.google.com, and grok.com, each signed in, in a
browser. Each evaluates it as a senior engineer and architect of
distributed agent platforms, scores it from 0 to 100, and sets it
beside its closest adjacents. Nothing is attached: each product reads
the repository itself. The method, and what a row means, are the
guideline's, in
[browser-judge-swe](https://github.com/baristaze/swe_guidelines/blob/v0.52.0/benchmark/runs/browser-judge-swe/README.md).
This page keeps what differs.

There is no judge. Each score is the product's own, from the answer. The
prompt is [prompt.md](../../browser/prompt.md), and it asks for a report
whose first line is `Score: NN/100`. The report has the sections of the
engine's, in
[browser-judge-agentic](https://github.com/baristaze/agentic_core/blob/main/benchmark/runs/browser-judge-agentic/README.md),
so the two read side by side. `distro-benchmark-browser` runs it and
checks each run in here. Two rows compare when their runs share the
sizes, the prompt, and the contract, as each `results.json` records
them; the Set column marks them.

Each run's folder holds its `results.json` and one answer per session,
redacted. An answer is the product's own Markdown from the copy button
under it, and its header says so where it is page text instead.
`[redacted]` marks each place a conversation's address, a name the
product knows the person by, a device's name, or the name of a
repository other than this one, the guideline, and the engine stood. No
screenshot is checked in.

The columns are the guideline's: the run's folder, its start, the commit
the repository stood at (`repository_head`), the sizes, one cell for
each product (the score linking the answer, then the model and effort
labels the page shows), the set, and a note. "—" marks what a run does
not record.

| Run | Started (UTC) | Head | Sizes | chatgpt.com | claude.ai | gemini.google.com | grok.com | Set | Note |
|---|---|---|---|---|---|---|---|---|---|
| [20261007-145111](20261007-145111/results.json) | 2026-10-07 14:51 | `76ed581` | m, m | — | [73](20261007-145111/claude.ai.md) Opus 5.5, High | — | — | A | — |
| [20261007-081415](20261007-081415/results.json) | 2026-10-07 08:14 | `9580f8f` | m, m | [89](20261007-081415/chatgpt.com.md) Latest, High | [not-run](20261007-081415/claude.ai.md) | [refused](20261007-081415/gemini.google.com.md) 3.1 Pro | [81](20261007-081415/grok.com.md) Expert | A | claude.ai: the conversation page said Computer actions available for a connected device; gemini.google.com: the product declined to evaluate |
