import { useAgentSessions } from "../../queries/agentSessions";
import { outageNotices } from "./outageModel";

/** The org's parked sessions, read as the sessions list reads them, and what
 * they wait on when it is a provider. A push that parks or wakes a session
 * reads them again. */
export function useOutageVm() {
  const parked = useAgentSessions("parked");
  return { notices: outageNotices(parked.data ?? []) };
}
