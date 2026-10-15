"""The tools the shipped kinds call, a module for each toolset whose tools
are the platform's own: `files`, `code`, `agent_knowledge`, `work_product`,
`records`, `handoff`, `review`, and `operations`. A tool no toolset holds
sits with the toolset it is closest to, and `base` holds what several
share. Each tool declares its class and its effect, which is all policy
reads of it, and takes a typed input that refuses a field it does not
declare: what a model writes is checked before any of it runs. A tool that
reads a manager takes it late, as a callable the root answers once it has
built it."""
