// The platform's own part of the portal, in the shape a product fills
// (`product.ts`): its pages, its entries in the left bar, its settings, the
// agents it ships, and the examples its fields show. The shell joins it with
// the product's and refuses an entry the two share.
import { ApprovalsPage } from "../features/approvals/ApprovalsPage";
import { AuditPage } from "../features/audit/AuditPage";
import { AutomationPage } from "../features/automations/AutomationPage";
import { AutomationsPage } from "../features/automations/AutomationsPage";
import { HomePage } from "../features/home/HomePage";
import { EntryPage } from "../features/knowledge/EntryPage";
import { KnowledgePage } from "../features/knowledge/KnowledgePage";
import { ModelsPage } from "../features/models/ModelsPage";
import { NewOrgPage } from "../features/new_org/NewOrgPage";
import { PlaybooksPage } from "../features/playbooks/PlaybooksPage";
import { ProjectPage } from "../features/projects/ProjectPage";
import { ProjectsPage } from "../features/projects/ProjectsPage";
import { SessionPage } from "../features/session/SessionPage";
import { SessionsPage } from "../features/sessions/SessionsPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { UsagePage } from "../features/usage/UsagePage";
import { AutomationIcon, BotIcon, DocumentIcon, KnowledgeIcon, ListIcon, ProjectIcon, ShieldIcon } from "../design/kit";
import { useKnowledge } from "../queries/knowledge";
import type { PortalProduct } from "./product";

/** How many suggested entries wait on a review; null until read. */
function useSuggestedCount(): number | null {
  return useKnowledge("suggested").data?.length ?? null;
}

export const PLATFORM: PortalProduct = {
  routes: [
    { path: "/", element: <HomePage /> },
    { path: "/sessions", element: <SessionsPage /> },
    { path: "/sessions/:sessionId", element: <SessionPage /> },
    { path: "/automations", element: <AutomationsPage /> },
    { path: "/automations/:automationId", element: <AutomationPage /> },
    { path: "/knowledge", element: <KnowledgePage /> },
    { path: "/knowledge/:entryId", element: <EntryPage /> },
    { path: "/approvals", element: <ApprovalsPage /> },
    { path: "/settings", element: <SettingsPage /> },
    { path: "/orgs/new", element: <NewOrgPage /> },
  ],
  nav: [
    {
      id: "automations",
      label: "Automations",
      icon: <AutomationIcon />,
      to: "/automations",
      tip: "What starts or messages a session on an event or a schedule",
    },
    {
      id: "knowledge",
      label: "Knowledge",
      icon: <KnowledgeIcon />,
      to: "/knowledge",
      tip: "What every session should know; the count is suggestions to review",
      count: useSuggestedCount,
    },
  ],
  sessionTabs: [],
  tools: {},
  settings: [
    {
      group: "Agents",
      id: "projects",
      label: "Projects",
      icon: <ProjectIcon />,
      about: "Each bound to its repository, and the credential it is read with",
      routes: [
        { path: "/projects", element: <ProjectsPage /> },
        { path: "/projects/:projectId", element: <ProjectPage /> },
      ],
    },
    {
      group: "Agents",
      id: "models",
      label: "Models and keys",
      icon: <BotIcon />,
      about: "The org's own provider keys, and its model for each role",
      routes: [{ path: "/models", element: <ModelsPage /> }],
    },
    {
      group: "Agents",
      id: "playbooks",
      label: "Playbooks",
      icon: <DocumentIcon />,
      about: "The team's procedures, as versioned briefs",
      routes: [{ path: "/playbooks", element: <PlaybooksPage /> }],
    },
    {
      group: "Organization",
      id: "usage",
      label: "Usage",
      icon: <ListIcon />,
      about: "Each budget and what its window spent",
      routes: [{ path: "/usage", element: <UsagePage /> }],
    },
    {
      group: "Organization",
      id: "audit",
      label: "Audit",
      icon: <ShieldIcon />,
      about: "What happened in the org, and who did it",
      routes: [{ path: "/audit", element: <AuditPage /> }],
    },
  ],
  agents: [
    { kind: "engineer", label: "Engineer", about: "Changes code in the project's repository, validates it, and opens a pull request." },
    { kind: "analysis", label: "Analysis", about: "Reads what a run produced and answers with findings; it changes nothing." },
    { kind: "planner", label: "Planner", about: "Turns findings into tasks, and hands engineering work to an engineer." },
    {
      kind: "platform_assistant",
      label: "Platform assistant",
      about: "Answers how the platform works and drafts configuration a person applies.",
    },
  ],
  examples: {
    composer: 'Describe a task, e.g. "Fix the failing test in tests/test_dates.py and open a pull request"',
    reply: 'Reply or steer, e.g. "Also add a test for leap years"',
    starters: [
      "Find why the nightly build fails and propose a fix",
      "Add a test for leap years to tests/test_dates.py",
      "Summarize what changed in the last ten merged pull requests",
    ],
  },
};
