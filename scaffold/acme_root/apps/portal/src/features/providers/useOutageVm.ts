import { useParkedSessions } from "../../queries/agentSessions";
import { outageNotices } from "./outageModel";

/** Every parked session of the org, page after page, and what they wait on
 * when it is a provider. A push that parks or wakes a session reads them
 * again. */
export function useOutageVm() {
  const parked = useParkedSessions();
  return { notices: outageNotices(parked.data ?? []) };
}
