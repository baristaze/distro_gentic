import type { MeView } from "@acme/client";
import { errorMessage } from "../../app/errorMessage";
import { useSsoLink } from "../../queries/tenancy";
import { useNoticesStore } from "../../store/notices";
import { ssoAvailable } from "./settingsModel";

/** A team org's single sign-on, for a member who manages members. The
 * identity provider hosts the page where an admin connects their own
 * identity provider, and sends the browser back here. */
export function useSignOnVm(me: MeView | undefined) {
  const ssoLink = useSsoLink();
  const notify = useNoticesStore((s) => s.notify);
  // The link is short-lived, so it is asked for on the click and followed at once.
  const open = async (intent: "sso" | "domain_verification") => {
    try {
      const link = await ssoLink.mutateAsync({ intent, return_url: `${window.location.origin}/settings/sign-on` });
      window.location.assign(link.url);
    } catch (caught) {
      notify(errorMessage(caught, "Single sign-on could not be opened."));
    }
  };
  return { available: ssoAvailable(me), open, opening: ssoLink.isPending };
}
