import { Fragment } from "react";
import { createBrowserRouter, Navigate, Outlet, useLocation, type RouteObject } from "react-router-dom";
import { CallbackPage } from "../features/sign_in/CallbackPage";
import { DevSignInPage } from "../features/sign_in/DevSignInPage";
import { LoginPage } from "../features/sign_in/LoginPage";
import { PRODUCT } from "../product";
import { RealtimeProvider } from "../realtime/RealtimeProvider";
import { useSessionStore } from "../store/session";
import { PLATFORM } from "./platform";
import { joinProducts, shellRoutes } from "./product";
import { RequireAuth } from "./RequireAuth";
import { RouteError } from "./RouteError";
import { Shell } from "./shell/Shell";
import { SlotProvider } from "./slot";
import { TimeZoneSync } from "./useTimeZoneSync";

/** The platform's entries and the product's, joined once at start: an entry
 * the two share stops the app here, before anything renders. */
export const SLOT = joinProducts(PLATFORM, PRODUCT);

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
          <SlotProvider slot={SLOT}>
            <Shell>
              <Outlet />
            </Shell>
          </SlotProvider>
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
    // The platform's pages and the product's, inside the shell.
    children: shellRoutes(SLOT),
  },
];

export const router = createBrowserRouter(routes);
