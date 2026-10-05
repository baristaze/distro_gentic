// The product's part of the portal: what it adds to the platform's pages,
// left bar, session tabs, tool cards, settings, agents, and examples, in the
// shape `app/product.ts` gives. The platform ships it empty and fills its
// own in `app/platform.tsx`; a product fills this one and edits no platform
// file. An entry whose id or address is the platform's is refused at start.
import type { PortalProduct } from "./app/product";

export const PRODUCT: PortalProduct = {
  routes: [], // its pages, inside the shell
  nav: [], // { id, label, icon, to, tip, count?() }: the left bar, under the platform's
  sessionTabs: [], // { id, label, icon, tip, offered(s), opensItself?(s), render(s) }
  tools: {}, // name -> { gist(input, output), card?(s, call), tab? }
  settings: [], // { group, id, label, icon, about, routes }
  agents: [], // { kind, label, about }: the first is the composer's default
  examples: {}, // { composer?, reply?, starters? }
};
