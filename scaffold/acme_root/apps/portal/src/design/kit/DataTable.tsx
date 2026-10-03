// A table of records: a column with a sort value sorts on a click of its
// header, which says how it is sorted (`aria-sort`), and a table with no
// rows says so in words.
import { useState, type ReactNode } from "react";
import { nextSort, sortRows, type Sort, type SortValue } from "./tableModel";

export interface Column<Row> {
  key: string;
  header: string;
  cell: (row: Row) => ReactNode;
  /** Present when the column sorts. */
  sortValue?: (row: Row) => SortValue;
}

export function DataTable<Row>({
  columns,
  rows,
  rowKey,
  empty,
  initialSort = null,
  label,
}: {
  columns: readonly Column<Row>[];
  rows: readonly Row[];
  rowKey: (row: Row) => string;
  /** What the table says when it has no rows. */
  empty: string;
  initialSort?: Sort | null;
  label?: string;
}) {
  const [sort, setSort] = useState<Sort | null>(initialSort);
  const sorting = sort ? columns.find((column) => column.key === sort.column) : undefined;
  const shown = sort && sorting?.sortValue ? sortRows(rows, sorting.sortValue, sort.direction) : [...rows];
  return (
    <table className="acme-table" aria-label={label}>
      <thead>
        <tr>
          {columns.map((column) => (
            <th key={column.key} aria-sort={sort?.column === column.key ? sort.direction : undefined}>
              {column.sortValue ? (
                <button type="button" className="acme-sort" onClick={() => setSort((current) => nextSort(current, column.key))}>
                  {column.header}
                  <span aria-hidden="true">{sort?.column === column.key ? (sort.direction === "ascending" ? " ↑" : " ↓") : ""}</span>
                </button>
              ) : (
                column.header
              )}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {shown.length === 0 ? (
          <tr>
            <td colSpan={columns.length} className="acme-table-empty">
              {empty}
            </td>
          </tr>
        ) : (
          shown.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((column) => (
                <td key={column.key}>{column.cell(row)}</td>
              ))}
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}
