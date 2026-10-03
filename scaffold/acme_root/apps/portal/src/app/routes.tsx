import { Fragment } from "react";
import { createBrowserRouter, Navigate, Outlet, useLocation, type RouteObject } from "react-router-dom";
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
import { CallbackPage } from "../features/sign_in/CallbackPage";
import { DevSignInPage } from "../features/sign_in/DevSignInPage";
import { LoginPage } from "../features/sign_in/LoginPage";
import { RealtimeProvider } from "../realtime/RealtimeProvider";
import { useSessionStore } from "../store/session";
import { RequireAuth } from "./RequireAuth";
import { RouteError } from "./RouteError";
import { TimeZoneSync } from "./useTimeZoneSync";

/** The signed-in app, mounted once per org. A switch keeps a token held
 * throughout (see adoptSession), so the shell is never torn down on its own;
 * the key does it. Every screen, its queries, its open dialogs and drafts,
 * and the realtime provider start over in the new org, and nothing the old
 * one rendered stays on screen. */
function AuthenticatedShell() {
  const orgSlug = useSessionStore((s) => s.orgSlug);
  return (
    <RequireAuth>
      <Fragment key={orgSlug}>
        <TimeZoneSync />
        <RealtimeProvider>
          <Outlet />
        </RealtimeProvider>
      </Fragment>
    </RequireAuth>
  );
}

/** A short address for the sign-in or the sign-up: it goes on to the
 * sign-in, keeping the page it was sent from. */
function GoOn({ to }: { to: string }) {
  const location = useLocation();
  return <Navigate to={to} replace state={location.state} />;
}

export const routes: RouteObject[] = [
  // The identity provider's "initiate login" address: it starts a sign-in at once.
  { path: "/login", element: <LoginPage />, errorElement: <RouteError /> },
  { path: "/login/dev", element: <DevSignInPage />, errorElement: <RouteError /> },
  // Where the identity provider's logout sends the browser back: a sign-in page that waits.
  { path: "/signed-out", element: <LoginPage signedOut />, errorElement: <RouteError /> },
  { path: "/auth/callback", element: <CallbackPage />, errorElement: <RouteError /> },
  { path: "/sign-in", element: <GoOn to="/login" />, errorElement: <RouteError /> },
  { path: "/sign-up", element: <GoOn to="/login?screen_hint=sign-up" />, errorElement: <RouteError /> },
  {
    element: <AuthenticatedShell />,
    errorElement: <RouteError />,
    children: [
      { path: "/", element: <HomePage /> },
      { path: "/sessions", element: <SessionsPage /> },
      { path: "/sessions/:sessionId", element: <SessionPage /> },
      { path: "/projects", element: <ProjectsPage /> },
      { path: "/projects/:projectId", element: <ProjectPage /> },
      { path: "/models", element: <ModelsPage /> },
      { path: "/automations", element: <AutomationsPage /> },
      { path: "/automations/:automationId", element: <AutomationPage /> },
      { path: "/playbooks", element: <PlaybooksPage /> },
      { path: "/knowledge", element: <KnowledgePage /> },
      { path: "/knowledge/:entryId", element: <EntryPage /> },
      { path: "/approvals", element: <ApprovalsPage /> },
      { path: "/audit", element: <AuditPage /> },
      { path: "/usage", element: <UsagePage /> },
      { path: "/settings", element: <SettingsPage /> },
      { path: "/orgs/new", element: <NewOrgPage /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
