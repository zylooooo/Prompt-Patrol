import { motion } from "framer-motion";
import LoadingState from "./LoadingState";
import { useMemo, type ReactNode } from "react";
import { useMediaQuery } from "../../hooks/useMediaQuery";
import { resolveGridColumnWidth } from "./data-table-columns";
import { useNarrowContainer } from "../../hooks/useNarrowContainer";
import { ChevronDown, ChevronsUpDown, ChevronUp } from "lucide-react";

export interface DataTableColumn<T> {
  id: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  width: string;
  hideWhenCompact?: boolean;
  sortKey?: string;
  align?: "left" | "right";
}

export type DataTableSortOrder = "asc" | "desc";
export const TABLE_ICON_COLUMN_WIDTH = "4.75rem";
export const TABLE_ACTION_COLUMN_WIDTH = "6.5rem";
export const TABLE_ACTIONS_WIDE_COLUMN_WIDTH = "16.5rem";

interface DataTableProps<T> {
  columns: readonly DataTableColumn<T>[];
  rows: readonly T[];
  getRowId: (row: T) => string;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  isCompact?: boolean;
  footer?: ReactNode;
  bodyMaxHeightClass?: string;
  fillHeight?: boolean;
  sort?: string | null;
  order?: DataTableSortOrder | null;
  onSort?: (sortKey: string) => void;
  exitingRowIds?: ReadonlySet<string>;
  emptyState?: ReactNode;
  isLoading?: boolean;
  loadingLabel?: string;
}

export default function DataTable<T>({
  columns,
  rows,
  getRowId,
  selectedId,
  onSelect,
  isCompact = false,
  footer,
  bodyMaxHeightClass,
  fillHeight = false,
  sort = null,
  order = null,
  onSort,
  exitingRowIds,
  emptyState,
  isLoading = false,
  loadingLabel = "Loading…",
}: DataTableProps<T>) {
  const isNarrowViewport = useMediaQuery("(max-width: 767px)");
  const { ref: containerRef, isNarrow: isNarrowContainer } = useNarrowContainer(
    COMPACT_CONTAINER_WIDTH,
  );
  const compact = isCompact || isNarrowViewport || isNarrowContainer;
  const template = columns
    .map((c) =>
      compact && c.hideWhenCompact
        ? "minmax(0,0fr)"
        : resolveGridColumnWidth(c.width),
    )
    .join(" ");

  const gridStyle = useMemo(
    () => ({ gridTemplateColumns: template }),
    [template],
  );

  const renderHeaderCell = (c: DataTableColumn<T>) => {
    const isHidden = compact && c.hideWhenCompact;
    const isSortable = !!c.sortKey && !!onSort;
    const isActiveSort = isSortable && c.sortKey === sort;
    const indicator = isActiveSort ? (
      order === "asc" ? (
        <ChevronUp className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
      ) : (
        <ChevronDown className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
      )
    ) : isSortable ? (
      <ChevronsUpDown
        className="h-3.5 w-3.5 text-disabled-foreground transition-colors group-hover:text-muted-foreground"
        aria-hidden="true"
      />
    ) : null;

    return (
      <div
        key={c.id}
        role="columnheader"
        aria-sort={
          isActiveSort
            ? order === "asc"
              ? "ascending"
              : "descending"
            : isSortable
              ? "none"
              : undefined
        }
        className={`${HEADER_CLASS}${c.align === "right" ? " justify-end" : ""}`}
      >
        {isHidden ? null : isSortable ? (
          <button
            type="button"
            onClick={() => onSort?.(c.sortKey!)}
            className={`group inline-flex items-center gap-1 text-left uppercase tracking-wide transition-colors hover:text-foreground focus-visible:text-foreground ${
              isActiveSort ? "text-foreground" : ""
            }`}
          >
            <span>{c.header}</span>
            {indicator}
          </button>
        ) : (
          c.header
        )}
      </div>
    );
  };

  const rowGridClass =
    "grid w-full transition-[grid-template-columns] duration-300 ease-out";
  const fills = fillHeight && !bodyMaxHeightClass;
  const isEmpty = rows.length === 0 && (emptyState || isLoading);

  return (
    <div
      ref={containerRef}
      className={`w-full overflow-hidden rounded-xl bg-surface shadow-md${
        fills ? " flex min-h-0 flex-1 flex-col" : ""
      }`}
    >
      <div
        role="table"
        className={`w-full overflow-x-auto${
          fills
            ? ` outline-hidden${isEmpty ? " shrink-0" : " min-h-0 flex-1 overflow-y-auto"}`
            : ""
        }`}
      >
        <div className="w-max min-w-full">
          <div
            role="row"
            style={gridStyle}
            className={`${rowGridClass} bg-surface-muted${
              fills && !isEmpty ? " sticky top-0 z-10" : ""
            }`}
          >
            {columns.map(renderHeaderCell)}
          </div>
          {!isEmpty ? (
            <div
              role="rowgroup"
              className={`divide-y divide-border/60${
                bodyMaxHeightClass
                  ? ` ${bodyMaxHeightClass} overflow-y-auto`
                  : ""
              }`}
            >
              {rows.map((row) => {
                const id = getRowId(row);
                const isSelected = id === selectedId;
                const isExiting = exitingRowIds?.has(id) ?? false;
                return (
                  <motion.div
                    key={id}
                    role="row"
                    aria-selected={isSelected}
                    animate={isExiting ? ROW_EXIT_ANIMATE : ROW_IDLE_ANIMATE}
                    transition={ROW_TRANSITION}
                    onClick={
                      onSelect && !isExiting ? () => onSelect(id) : undefined
                    }
                    style={gridStyle}
                    className={`${rowGridClass} group hover:bg-surface-muted/50 ${
                      isExiting ? "pointer-events-none overflow-hidden" : ""
                    } ${onSelect && !isExiting ? "cursor-pointer" : ""} ${
                      isSelected
                        ? "bg-primary-soft/40 [&_[role=cell]]:text-accent"
                        : onSelect
                          ? "hover:bg-surface-muted/70"
                          : ""
                    }`}
                  >
                    {columns.map((c, idx) => {
                      const isHidden = compact && c.hideWhenCompact;
                      return (
                        <div
                          key={c.id}
                          role="cell"
                          className={`${CELL_CLASS}${
                            c.align === "right" ? " justify-end" : ""
                          }`}
                        >
                          {idx === 0 && (
                            <span
                              aria-hidden="true"
                              className={`h-4 shrink-0 rounded-full bg-primary transition-[width,margin-right,opacity] duration-300 ease-out ${
                                isSelected
                                  ? "mr-2 w-0.5 opacity-100"
                                  : "mr-0 w-0 opacity-0"
                              }`}
                            />
                          )}
                          {isHidden ? null : c.cell(row)}
                        </div>
                      );
                    })}
                  </motion.div>
                );
              })}
            </div>
          ) : null}
        </div>
      </div>
      {isEmpty ? (
        isLoading ? (
          <LoadingState
            size="card"
            label={loadingLabel}
            className={fills ? "min-h-0 flex-1" : ""}
          />
        ) : (
          <div
            className={`flex w-full items-center justify-center px-4 text-center text-sm text-muted-foreground ${
              fills ? "min-h-0 flex-1" : "py-12"
            }`}
          >
            {emptyState}
          </div>
        )
      ) : null}
      {footer && (
        <div className="shrink-0 border-t border-border bg-surface-muted/70 px-5 py-2 text-left text-xs text-foreground">
          {footer}
        </div>
      )}
    </div>
  );
}

const ROW_EXIT_ANIMATE = { height: 0, opacity: 0 };
const ROW_IDLE_ANIMATE = { opacity: 1 };
const ROW_TRANSITION = { duration: 0.25, ease: [0.4, 0, 0.2, 1] as const };
const COMPACT_CONTAINER_WIDTH = 640;
const CELL_CLASS =
  "flex items-center whitespace-nowrap overflow-hidden px-3 py-4 text-left text-sm font-medium text-foreground sm:px-5";
const HEADER_CLASS =
  "flex items-center whitespace-nowrap overflow-hidden px-3 py-3 text-left text-xs font-bold uppercase tracking-wide text-muted-foreground sm:px-5";
