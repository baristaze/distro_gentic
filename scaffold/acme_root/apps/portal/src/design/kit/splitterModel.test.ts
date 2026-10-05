// A pane's width stays inside its bounds however its edge moves: a drag, an
// arrow, Home, End, or a stored width that is out of range or not a number.
import { expect, it } from "vitest";
import { clampWidth, draggedWidth, KEY_STEP, keyedWidth } from "./splitterModel";
import { tipPlace } from "./tooltipModel";

const bounds = { min: 200, max: 420, initial: 260 };

it("keeps a width inside the bounds, and an unreadable one at the first width", () => {
  expect(clampWidth(100, bounds)).toBe(200);
  expect(clampWidth(900, bounds)).toBe(420);
  expect(clampWidth(300.4, bounds)).toBe(300);
  expect(clampWidth(Number.NaN, bounds)).toBe(260);
});

it("follows the pointer from where the drag started, the other way for a handle on the left", () => {
  expect(draggedWidth(260, 500, 540, bounds)).toBe(300);
  expect(draggedWidth(260, 500, 100, bounds)).toBe(200);
  expect(draggedWidth(260, 500, 540, bounds, "left")).toBe(220);
});

it("moves by a step on an arrow, to an end on Home or End, and ignores any other key", () => {
  expect(keyedWidth(260, "ArrowRight", bounds)).toBe(260 + KEY_STEP);
  expect(keyedWidth(260, "ArrowLeft", bounds)).toBe(260 - KEY_STEP);
  expect(keyedWidth(260, "ArrowLeft", bounds, "left")).toBe(260 + KEY_STEP);
  expect(keyedWidth(410, "ArrowRight", bounds)).toBe(420);
  expect(keyedWidth(260, "Home", bounds)).toBe(200);
  expect(keyedWidth(260, "End", bounds)).toBe(420);
  expect(keyedWidth(260, "a", bounds)).toBeNull();
});

it("floats a tip outside the control's edge on the side it names", () => {
  const rect = { top: 100, bottom: 120, left: 10, right: 50 };
  expect(tipPlace(rect, "bottom")).toMatchObject({ position: "fixed", left: 30, top: 126 });
  expect(tipPlace(rect, "top")).toMatchObject({ left: 30, top: 94, transform: "translate(-50%, -100%)" });
  expect(tipPlace(rect, "right")).toMatchObject({ left: 56, top: 110 });
  expect(tipPlace(rect, "left")).toMatchObject({ left: 4, top: 110, transform: "translate(-100%, -50%)" });
});
