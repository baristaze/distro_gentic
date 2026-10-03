// What a dialog over the page needs from the keyboard: the things Tab moves
// through inside it, and the way back to what held the keyboard before it.
import { useEffect } from "react";

/** The focusable things inside an element, in order: what Tab moves through. */
export function focusables(root: HTMLElement | null): HTMLElement[] {
  if (!root) return [];
  return [
    ...root.querySelectorAll<HTMLElement>("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])"),
  ].filter((element) => !(element as HTMLButtonElement).disabled);
}

/** Puts the keyboard back on what held it when the component mounted, once
 * the component goes. */
export function useReturnFocus(): void {
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    return () => before?.focus?.();
  }, []);
}

/** Keeps Tab inside a dialog: from its last focusable thing Tab goes to its
 * first, and Shift-Tab from its first to its last. */
export function keepTabInside(event: { key: string; shiftKey: boolean; preventDefault: () => void }, root: HTMLElement | null): void {
  if (event.key !== "Tab") return;
  const items = focusables(root);
  const first = items[0];
  const last = items[items.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last?.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first?.focus();
  }
}
