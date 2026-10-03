// @vitest-environment jsdom
// The palette: Cmd-K or Ctrl-K opens it, typing narrows it best first, the
// arrows choose, and Enter does the chosen command and closes.
import { act, createElement, useState } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { CommandPalette, usePaletteKey } from "./CommandPalette";
import { matchScore, opensPalette, paletteStep, rankCommands } from "./overlayModel";

vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const COMMANDS = [
  { id: "pause", label: "Pause the session" },
  { id: "take", label: "Take control", keywords: ["terminal"] },
  { id: "archive", label: "Archive the session" },
];

describe("ranking", () => {
  it("keeps every command in order with no query, and only the matches with one", () => {
    expect(rankCommands(COMMANDS, "").map((c) => c.id)).toEqual(["pause", "take", "archive"]);
    expect(rankCommands(COMMANDS, "arch").map((c) => c.id)).toEqual(["archive"]);
    expect(rankCommands(COMMANDS, "term").map((c) => c.id)).toEqual(["take"]);
  });

  it("scores a run of letters at a word's start above scattered ones", () => {
    expect(matchScore("Take control", "con")!).toBeGreaterThan(matchScore("Take control", "tcl")!);
    expect(matchScore("Take control", "xyz")).toBeNull();
  });

  it("opens on Cmd-K or Ctrl-K, and wraps the arrows", () => {
    expect([opensPalette({ key: "k", metaKey: true, ctrlKey: false }), opensPalette({ key: "K", metaKey: false, ctrlKey: true }), opensPalette({ key: "k", metaKey: false, ctrlKey: false })]).toEqual([true, true, false]);
    expect([paletteStep(2, 3, "ArrowDown"), paletteStep(0, 3, "ArrowUp"), paletteStep(0, 0, "ArrowDown")]).toEqual([0, 2, null]);
  });
});

describe("CommandPalette", () => {
  it("opens on Ctrl-K, narrows as one types, and runs the chosen command on Enter", async () => {
    const ran: string[] = [];
    function Harness() {
      const [open, setOpen] = useState(false);
      usePaletteKey(() => setOpen(true));
      const commands = COMMANDS.map((command) => ({ ...command, run: () => ran.push(command.id) }));
      return open ? createElement(CommandPalette, { commands, onClose: () => setOpen(false) }) : null;
    }
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    await act(async () => root.render(createElement(Harness)));
    expect(container.querySelector("[role='dialog']")).toBeNull();
    await act(async () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true })));
    const field = container.querySelector<HTMLInputElement>("[role='combobox']")!;
    expect(document.activeElement).toBe(field);
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    await act(async () => {
      setter.call(field, "session");
      field.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect([...container.querySelectorAll("[role='option']")].map((o) => o.textContent)).toEqual(["Pause the session", "Archive the session"]);
    await act(async () => field.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })));
    await act(async () => field.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    expect(ran).toEqual(["archive"]);
    expect(container.querySelector("[role='dialog']")).toBeNull();
    await act(async () => root.unmount());
    container.remove();
  });
});
