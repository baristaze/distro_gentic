// Pure: where a tooltip floats beside the control it describes. It is drawn
// fixed to the window, so a pane that scrolls or clips never cuts it.
import type { CSSProperties } from "react";

export type TipSide = "top" | "bottom" | "left" | "right";

/** The gap between a control's edge and its tip, in pixels. */
export const TIP_GAP = 6;

/** The tip's place for a control at `rect`: centred on the side it names,
 * the transform moving it by its own size so no measure of it is needed. */
export function tipPlace(rect: { top: number; bottom: number; left: number; right: number }, side: TipSide): CSSProperties {
  const middleX = (rect.left + rect.right) / 2;
  const middleY = (rect.top + rect.bottom) / 2;
  switch (side) {
    case "top":
      return { position: "fixed", left: middleX, top: rect.top - TIP_GAP, transform: "translate(-50%, -100%)" };
    case "bottom":
      return { position: "fixed", left: middleX, top: rect.bottom + TIP_GAP, transform: "translate(-50%, 0)" };
    case "left":
      return { position: "fixed", left: rect.left - TIP_GAP, top: middleY, transform: "translate(-100%, -50%)" };
    case "right":
      return { position: "fixed", left: rect.right + TIP_GAP, top: middleY, transform: "translate(0, -50%)" };
  }
}
