// @vitest-environment jsdom
// One of a set over the page: the arrows wrap around, Escape closes it, and
// a set of one has no way to the next.
import { act, createElement, useState } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { Lightbox } from "./Lightbox";
import { lightboxStep } from "./overlayModel";

vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

describe("lightboxStep", () => {
  it("wraps the arrows around and goes to the ends on Home and End", () => {
    expect([lightboxStep(2, 3, "ArrowRight"), lightboxStep(0, 3, "ArrowLeft"), lightboxStep(1, 3, "Home"), lightboxStep(0, 3, "End")]).toEqual([0, 2, 0, 2]);
    expect([lightboxStep(0, 1, "ArrowRight"), lightboxStep(0, 3, "a")]).toEqual([null, null]);
  });
});

describe("Lightbox", () => {
  it("moves with the arrows, counts where it is, and closes on Escape", async () => {
    const onClose = vi.fn();
    function Harness() {
      const [index, setIndex] = useState(0);
      const items = ["one", "two", "three"].map((title) => ({ title, content: createElement("p", null, `${title} body`) }));
      return createElement(Lightbox, { items, index, onIndex: setIndex, onClose });
    }
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    await act(async () => root.render(createElement(Harness)));
    const dialog = () => container.querySelector("[role='dialog']")!;
    expect(dialog().getAttribute("aria-label")).toBe("one");
    expect(document.activeElement!.textContent).toBe("Close");
    await act(async () => dialog().dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true })));
    expect(dialog().getAttribute("aria-label")).toBe("three");
    expect(container.textContent).toContain("3 of 3");
    await act(async () => dialog().dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
    expect(onClose).toHaveBeenCalledOnce();
    await act(async () => root.unmount());
    container.remove();
  });
});
