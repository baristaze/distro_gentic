import { useMemo } from "react";
import { useParkedSessions, useTrees } from "../../queries/agentSessions";
import { outageNotices } from "./outageModel";

/** Every parked session of the org, page after page, and what they wait on
 * when it is a provider. The list holds roots alone, so the sub-agents
 * beneath each parked root are read too: one parked on a provider under a
 * root that waits on its children counts. A push that parks or wakes a
 * session reads them again. */
export function useOutageVm() {
  const parked = useParkedSessions("visible");
  const roots = parked.data;
  const trees = useTrees(roots ?? []);
  const sessions = useMemo(() => [...(roots ?? []), ...trees], [roots, trees]);
  return { notices: outageNotices(sessions) };
}
