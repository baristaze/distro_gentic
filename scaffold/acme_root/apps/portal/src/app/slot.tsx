// The joined slot, the platform's entries and the product's, as the shell
// hands it to every screen inside it. A screen reads it from here rather
// than importing the product, so a test gives a screen the slot it needs.
import { createContext, useContext, type ReactNode } from "react";
import { EMPTY_PRODUCT, type PortalProduct } from "./product";

const SlotContext = createContext<PortalProduct>(EMPTY_PRODUCT);

export function SlotProvider({ slot, children }: { slot: PortalProduct; children: ReactNode }) {
  return <SlotContext.Provider value={slot}>{children}</SlotContext.Provider>;
}

export function useSlot(): PortalProduct {
  return useContext(SlotContext);
}
