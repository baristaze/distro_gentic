// The session's page hands its view-model to the platform's own tabs, which
// the pane draws through the slot in the shape a product's take: a tab
// gets the session as `SlotSession`, and a platform tab reads the rest of
// the page from here, so the page's reads and actions are made once.
import { createContext, useContext } from "react";
import type { SessionVm } from "./useSessionVm";

export const SessionVmContext = createContext<SessionVm | null>(null);

export function useSessionPage(): SessionVm {
  const vm = useContext(SessionVmContext);
  if (vm === null) throw new Error("A session's tab draws inside the session's page.");
  return vm;
}
