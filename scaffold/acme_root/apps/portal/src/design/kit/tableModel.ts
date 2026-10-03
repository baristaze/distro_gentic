// Pure: the order a table's rows show in. A value that is missing sorts
// last whichever way the column runs, numbers sort as numbers, and words as
// a person reads them ("run 2" before "run 10"). Rows that tie keep their
// order.

export type SortDirection = "ascending" | "descending";
export type SortValue = string | number | null | undefined;

export interface Sort {
  column: string;
  direction: SortDirection;
}

const WORDS = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

function compare(a: SortValue, b: SortValue): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return WORDS.compare(String(a), String(b));
}

export function sortRows<Row>(rows: readonly Row[], value: (row: Row) => SortValue, direction: SortDirection): Row[] {
  const sign = direction === "ascending" ? 1 : -1;
  return [...rows].sort((left, right) => {
    const a = value(left);
    const b = value(right);
    const aMissing = a === null || a === undefined || a === "";
    const bMissing = b === null || b === undefined || b === "";
    if (aMissing || bMissing) return Number(aMissing) - Number(bMissing);
    return sign * compare(a, b);
  });
}

/** A click on a column's header: the same column turns around, another
 * starts ascending. */
export function nextSort(current: Sort | null, column: string): Sort {
  if (current?.column === column) {
    return { column, direction: current.direction === "ascending" ? "descending" : "ascending" };
  }
  return { column, direction: "ascending" };
}
