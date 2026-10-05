# The portal's pages

<!-- Generated from the portal's route catalog (apps/portal/src/app/routeCatalog.ts);
     its test fails while this file differs, and `vitest run -u` writes it again. -->

Every page of the portal, by its address, with what it shows. Link a
page with a Markdown link whose target is its address, each `:name`
filled in as its line says: `/sessions/<id>` for one session. In the
support dock, a link to one of these addresses opens its page beside the
conversation; any other link shows as text.

A message sent from the dock ends with a `page` block: the address the
person is on, the route it matched, and the parameters it named, as data.

| Address | What it shows | Parameters |
| --- | --- | --- |
| `/` | Home: a box to describe a task, the agent and the project it starts on, and starter prompts |  |
| `/sessions` | All sessions of the org, filtered by status, by whose, by agent, and by title; `?needs=you` shows the ones waiting on you |  |
| `/sessions/:sessionId` | One session: its status and what it waits on, its chat, and a pane of what it did (its steps, workspace, changes, evidence, and sub-agents) | `sessionId`: the session's id |
| `/automations` | The org's automations, a new one, and the automation principal |  |
| `/automations/:automationId` | One automation: its state, what fires it, what it does, its limits, whom it runs as, its brief, and its edit | `automationId`: the automation's id |
| `/knowledge` | Knowledge: what every session should know, and the suggestions waiting on a review |  |
| `/knowledge/:entryId` | One knowledge entry, its review, and its edit | `entryId`: the entry's id |
| `/settings` | Settings: every section, by group |  |
| `/orgs/new` | A new org of the signed-in person's own |  |
| `/projects` | An old address: it lands on `/settings/projects` |  |
| `/projects/:projectId` | An old address: it lands on `/settings/projects/:projectId` | `projectId`: as `/settings/projects/:projectId` names it |
| `/models` | An old address: it lands on `/settings/models` |  |
| `/playbooks` | An old address: it lands on `/settings/playbooks` |  |
| `/audit` | An old address: it lands on `/settings/audit` |  |
| `/usage` | An old address: it lands on `/settings/usage` |  |
| `/approvals` | An old address: it lands on `/sessions?needs=you` |  |
| `/settings/profile` | Settings › Profile: Your name, the theme, and your account |  |
| `/settings/general` | Settings › General: The org's name, its storage, and its deletion |  |
| `/settings/members` | Settings › Members: Who is in the org, their roles, and invitations |  |
| `/settings/usage` | Settings › Usage: Each budget and what its window spent |  |
| `/settings/audit` | Settings › Audit: What happened in the org, and who did it |  |
| `/settings/projects` | Settings › Projects: Each bound to its repository, and the credential it is read with |  |
| `/settings/projects/:projectId` | One project: its repository, the credential it is read with, its name, and its removal | `projectId`: the project's id |
| `/settings/models` | Settings › Models and keys: The org's own provider keys, and its model for each role |  |
| `/settings/playbooks` | Settings › Playbooks: The team's procedures, as versioned briefs |  |
| `/settings/api-keys` | Settings › API keys: Keys a program calls the API with, as the org |  |
| `/settings/sign-on` | Settings › Single sign-on: Sign-in through the org's own identity provider |  |
