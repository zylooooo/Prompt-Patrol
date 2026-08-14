import type { ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

interface PaginationProps {
  page: number;
  totalPages: number;
  total: number;
  pageSize: number;
  onPageChange: (next: number) => void;
  disabled?: boolean;
  itemNoun?: string;
}

export default function Pagination({
  page,
  totalPages,
  total,
  pageSize,
  onPageChange,
  disabled = false,
  itemNoun = "results",
}: PaginationProps) {
  if (total === 0) return null;

  const clampedPage = Math.min(Math.max(1, page), totalPages);
  const from = (clampedPage - 1) * pageSize + 1;
  const to = Math.min(clampedPage * pageSize, total);

  const showPager = totalPages > 1;
  const pageItems = showPager ? buildPageList(clampedPage, totalPages) : [];

  const go = (next: number) => {
    if (disabled) return;
    const target = Math.min(Math.max(1, next), totalPages);
    if (target !== clampedPage) onPageChange(target);
  };

  return (
    <nav
      aria-label="Pagination"
      className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
    >
      <p className="text-sm text-muted-foreground">
        Showing{" "}
        <span className="font-semibold text-foreground">
          {from.toLocaleString()}{" "}
          {from !== to ? `– ${to.toLocaleString()}` : ""}
        </span>{" "}
        of{" "}
        <span className="font-semibold text-foreground">
          {total.toLocaleString()}
        </span>{" "}
        {itemNoun}
      </p>

      {showPager && (
        <div className="flex flex-wrap items-center gap-1">
          <PagerButton
            ariaLabel="Previous page"
            onClick={() => go(clampedPage - 1)}
            disabled={disabled || clampedPage <= 1}
          >
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          </PagerButton>

          {pageItems.map((item, idx) =>
            item === "ellipsis" ? (
              <span
                key={`ellipsis-${idx}`}
                aria-hidden="true"
                className="px-1 text-disabled-foreground select-none"
              >
                …
              </span>
            ) : (
              <PageNumberButton
                key={item}
                page={item}
                isCurrent={item === clampedPage}
                onClick={() => go(item)}
                disabled={disabled}
              />
            ),
          )}

          <PagerButton
            ariaLabel="Next page"
            onClick={() => go(clampedPage + 1)}
            disabled={disabled || clampedPage >= totalPages}
          >
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </PagerButton>
        </div>
      )}
    </nav>
  );
}

interface PagerButtonProps {
  ariaLabel: string;
  onClick: () => void;
  disabled: boolean;
  children: ReactNode;
}

function PagerButton({
  ariaLabel,
  onClick,
  disabled,
  children,
}: PagerButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border bg-surface text-muted-foreground transition-colors hover:bg-surface-muted hover:text-foreground focus:outline-hidden focus-visible:ring-2 focus-visible:ring-focus-ring/30 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-surface disabled:hover:text-muted-foreground"
    >
      {children}
    </button>
  );
}

interface PageNumberButtonProps {
  page: number;
  isCurrent: boolean;
  onClick: () => void;
  disabled: boolean;
}

function PageNumberButton({
  page,
  isCurrent,
  onClick,
  disabled,
}: PageNumberButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || isCurrent}
      aria-current={isCurrent ? "page" : undefined}
      aria-label={
        isCurrent ? `Page ${page}, current page` : `Go to page ${page}`
      }
      className={
        isCurrent
          ? "inline-flex h-8 min-w-[2rem] items-center justify-center rounded-md bg-primary px-2 text-sm font-semibold text-primary-foreground"
          : "inline-flex h-8 min-w-[2rem] items-center justify-center rounded-md border border-transparent px-2 text-sm font-medium text-muted-foreground transition-colors hover:border-border hover:bg-surface-muted focus:outline-hidden focus-visible:ring-2 focus-visible:ring-focus-ring/30 disabled:cursor-not-allowed disabled:opacity-40"
      }
    >
      {page}
    </button>
  );
}

function buildPageList(
  current: number,
  totalPages: number,
): (number | "ellipsis")[] {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }

  const anchors = new Set<number>([
    1,
    totalPages,
    current,
    current - 1,
    current + 1,
  ]);
  const sorted = [...anchors]
    .filter((p) => p >= 1 && p <= totalPages)
    .sort((a, b) => a - b);

  const result: (number | "ellipsis")[] = [];
  let prev = 0;
  for (const p of sorted) {
    if (p === prev + 2) {
      result.push(prev + 1);
    } else if (p > prev + 1) {
      result.push("ellipsis");
    }
    result.push(p);
    prev = p;
  }
  return result;
}
