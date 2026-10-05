// The platform's own part of the portal, in the shape a product fills
// (`product.ts`): its pages, its entries in the left bar, its settings, the
// agents it ships, and the examples its fields show. The shell joins it with
// the product's and refuses an entry the two share.
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
import { ApiKeysPage } from "../features/settings/ApiKeysPage";
import { GeneralPage } from "../features/settings/GeneralPage";
import { MembersPage } from "../features/settings/MembersPage";
import { ProfilePage } from "../features/settings/ProfilePage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { SignOnPage } from "../features/settings/SignOnPage";
import { UsagePage } from "../features/usage/UsagePage";
import {
  AuditIcon,
  AutomationIcon,
  BotIcon,
  DocumentIcon,
  KeyIcon,
  KnowledgeIcon,
  OrgIcon,
  ProjectIcon,
  SignOnIcon,
  UsageIcon,
  UserIcon,
  UsersIcon,
} from "../design/kit";
import { useKnowledge } from "../queries/knowledge";
import { Moved } from "./Moved";
import type { PortalProduct } from "./product";

/** How many suggested entries wait on a review; null until read. */
function useSuggestedCount(): number | null {
  return useKnowledge("suggested").data?.length ?? null;
}

/** The addresses the portal moved, and where each lands now: what is set up
 * once went under Settings, and the calls waiting on a person are the
 * sessions that need one. A `:name` in the new address takes the old one's. */
export const MOVED: readonly { from: string; to: string }[] = [
  { from: "/projects", to: "/settings/projects" },
  { from: "/projects/:projectId", to: "/settings/projects/:projectId" },
  { from: "/models", to: "/settings/models" },
  { from: "/playbooks", to: "/settings/playbooks" },
  { from: "/audit", to: "/settings/audit" },
  { from: "/usage", to: "/settings/usage" },
  { from: "/approvals", to: "/sessions?needs=you" },
];

export const PLATFORM: PortalProduct = {
  routes: [
    { path: "/", element: <HomePage /> },
    { path: "/sessions", element: <SessionsPage /> },
    { path: "/sessions/:sessionId", element: <SessionPage /> },
    { path: "/automations", element: <AutomationsPage /> },
    { path: "/automations/:automationId", element: <AutomationPage /> },
    { path: "/knowledge", element: <KnowledgePage /> },
    { path: "/knowledge/:entryId", element: <EntryPage /> },
    { path: "/settings", element: <SettingsPage /> },
    { path: "/orgs/new", element: <NewOrgPage /> },
    ...MOVED.map(({ from, to }) => ({ path: from, element: <Moved to={to} /> })),
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
      group: "Personal",
      id: "profile",
      label: "Profile",
      icon: <UserIcon />,
      about: "Your name, the theme, and your account",
      routes: [{ path: "/settings/profile", element: <ProfilePage /> }],
    },
    {
      group: "Organization",
      id: "general",
      label: "General",
      icon: <OrgIcon />,
      about: "The org's name, its storage, and its deletion",
      routes: [{ path: "/settings/general", element: <GeneralPage /> }],
    },
    {
      group: "Organization",
      id: "members",
      label: "Members",
      icon: <UsersIcon />,
      about: "Who is in the org, their roles, and invitations",
      routes: [{ path: "/settings/members", element: <MembersPage /> }],
    },
    {
      group: "Organization",
      id: "usage",
      label: "Usage",
      icon: <UsageIcon />,
      about: "Each budget and what its window spent",
      routes: [{ path: "/settings/usage", element: <UsagePage /> }],
    },
    {
      group: "Organization",
      id: "audit",
      label: "Audit",
      icon: <AuditIcon />,
      about: "What happened in the org, and who did it",
      routes: [{ path: "/settings/audit", element: <AuditPage /> }],
    },
    {
      group: "Agents",
      id: "projects",
      label: "Projects",
      icon: <ProjectIcon />,
      about: "Each bound to its repository, and the credential it is read with",
      routes: [
        { path: "/settings/projects", element: <ProjectsPage /> },
        { path: "/settings/projects/:projectId", element: <ProjectPage /> },
      ],
    },
    {
      group: "Agents",
      id: "models",
      label: "Models and keys",
      icon: <BotIcon />,
      about: "The org's own provider keys, and its model for each role",
      routes: [{ path: "/settings/models", element: <ModelsPage /> }],
    },
    {
      group: "Agents",
      id: "playbooks",
      label: "Playbooks",
      icon: <DocumentIcon />,
      about: "The team's procedures, as versioned briefs",
      routes: [{ path: "/settings/playbooks", element: <PlaybooksPage /> }],
    },
    {
      group: "Security",
      id: "api-keys",
      label: "API keys",
      icon: <KeyIcon />,
      about: "Keys a program calls the API with, as the org",
      routes: [{ path: "/settings/api-keys", element: <ApiKeysPage /> }],
    },
    {
      group: "Security",
      id: "sign-on",
      label: "Single sign-on",
      icon: <SignOnIcon />,
      about: "Sign-in through the org's own identity provider",
      routes: [{ path: "/settings/sign-on", element: <SignOnPage /> }],
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
