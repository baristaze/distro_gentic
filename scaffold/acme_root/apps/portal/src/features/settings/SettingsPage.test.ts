// @vitest-environment jsdom
// Settings' overview: a card for each group of the slot's sections, the
// platform's and a product's alike, each section linked with what it holds.
// It holds no signed-in line and no Sign out: those are the account menu's.
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { EMPTY_PRODUCT, joinProducts, type PortalProduct } from "../../app/product";
import { SlotProvider } from "../../app/slot";
import { SettingsPage } from "./SettingsPage";

vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const section = (group: string, id: string, label: string, about: string) => ({
  group,
  id,
  label,
  icon: null,
  about,
  routes: [{ path: `/settings/${id}` }],
});
const PLATFORM: PortalProduct = {
  ...EMPTY_PRODUCT,
  settings: [section("Personal", "profile", "Profile", "Your name"), section("Security", "api-keys", "API keys", "Keys a program calls with")],
};
const PRODUCT: PortalProduct = { ...EMPTY_PRODUCT, settings: [section("Places", "places", "Places", "Where work runs")] };

const container = document.createElement("div");
document.body.append(container);
let root: ReturnType<typeof createRoot>;

beforeEach(async () => {
  const router = createMemoryRouter([{ path: "/settings", Component: SettingsPage }], { initialEntries: ["/settings"] });
  root = createRoot(container);
  const slot = joinProducts(PLATFORM, PRODUCT);
  await act(async () => root.render(createElement(SlotProvider, { slot, children: createElement(RouterProvider, { router }) })));
});
afterEach(async () => {
  await act(async () => root.render(null));
});

it("is titled Settings and holds a card for each group, the product's after the platform's", () => {
  expect(container.querySelector("h1")!.textContent).toBe("Settings");
  expect([...container.querySelectorAll("h2")].map((h) => h.textContent)).toEqual(["Personal", "Security", "Places"]);
  const links = [...container.querySelectorAll("a")].map((a) => [a.getAttribute("href"), a.textContent]);
  expect(links).toEqual([
    ["/settings/profile", "ProfileYour name"],
    ["/settings/api-keys", "API keysKeys a program calls with"],
    ["/settings/places", "PlacesWhere work runs"],
  ]);
});

it("has no signed-in line and no Sign out", () => {
  expect(container.textContent).not.toContain("Signed in");
  expect([...container.querySelectorAll("button")].some((b) => b.textContent === "Sign out")).toBe(false);
});
