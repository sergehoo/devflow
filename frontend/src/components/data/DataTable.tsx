import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Tableau TanStack piloté par le serveur : tri → paramètre DRF `ordering`
 * (`champ` / `-champ`), pagination gérée par l'appelant.
 * Une colonne est triable si `meta.sortKey` est défini.
 */
export function DataTable<T>({ columns, data, ordering, onOrderingChange, caption, rowKey }: {
  columns: ColumnDef<T, unknown>[];
  data: T[];
  ordering?: string;
  onOrderingChange?: (ordering: string) => void;
  caption: string;
  rowKey: (row: T) => string | number;
}) {
  // eslint-disable-next-line react-hooks/incompatible-library -- API TanStack Table, mémoïsation gérée par la lib
  const table = useReactTable({ data, columns, getCoreRowModel: getCoreRowModel(), manualSorting: true, getRowId: (r) => String(rowKey(r)) });
  return (
    <div className="overflow-x-auto rounded-2xl border bg-card">
      <table className="w-full min-w-[720px] text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="border-b bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((h) => {
                const sortKey = (h.column.columnDef.meta as { sortKey?: string } | undefined)?.sortKey;
                const label = flexRender(h.column.columnDef.header, h.getContext());
                const dir = ordering === sortKey ? "asc" : ordering === `-${sortKey}` ? "desc" : null;
                return (
                  <th key={h.id} scope="col" className="px-4 py-3 font-semibold" aria-sort={dir === "asc" ? "ascending" : dir === "desc" ? "descending" : undefined}>
                    {sortKey && onOrderingChange ? (
                      <button type="button" className="inline-flex items-center gap-1 hover:text-foreground"
                        onClick={() => onOrderingChange(dir === "asc" ? `-${sortKey}` : dir === "desc" ? "" : sortKey)}>
                        {label}
                        {dir === "asc" ? <ArrowUp className="size-3.5" /> : dir === "desc" ? <ArrowDown className="size-3.5" /> : <ArrowUpDown className="size-3.5 opacity-40" />}
                      </button>
                    ) : label}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody className="divide-y">
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id} className="hover:bg-muted/40">
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className={cn("px-4 py-3 align-middle")}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
