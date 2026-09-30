"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Button, Input, Spinner } from "@/components/ui";
import type { Page } from "@/lib/api";

/** Search box that reports the text once typing pauses, so each keystroke is not a request. */
export function SearchInput({ onSearch, placeholder = "Search" }: { onSearch: (text: string) => void; placeholder?: string }) {
  const [text, setText] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => onSearch(text.trim()), 300);
    return () => clearTimeout(timer);
  }, [text, onSearch]);

  return (
    <div className="relative w-full sm:w-64">
      <Input type="search" aria-label={placeholder} placeholder={placeholder} value={text} maxLength={100} onChange={(e) => setText(e.target.value)} />
    </div>
  );
}

/** Placeholder rows shown while the first page of a list is loading. */
export function ListSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div role="status" aria-label="Loading" className="space-y-2">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="animate-pulse rounded-lg border border-zinc-200 bg-white p-4">
          <div className="h-4 w-2/5 rounded bg-zinc-200" />
          <div className="mt-3 h-3 w-4/5 rounded bg-zinc-100" />
          <div className="mt-2 h-3 w-3/5 rounded bg-zinc-100" />
        </div>
      ))}
    </div>
  );
}

/** A list area: a skeleton on first load, then the content, dimmed while a newer result is on its way. */
export function ListBody({ loading, fetching, rows, children }: { loading: boolean; fetching: boolean; rows?: number; children: ReactNode }) {
  if (loading) return <ListSkeleton rows={rows} />;
  // The delay keeps a fast response from flashing.
  return (
    <div aria-busy={fetching} className={`transition-opacity ${fetching ? "opacity-60 delay-150" : ""}`}>
      {children}
    </div>
  );
}

export function Pagination<T>({
  data,
  fetching = false,
  onPage,
}: {
  data: Page<T> | undefined;
  fetching?: boolean;
  onPage: (page: number) => void;
}) {
  if (!data || data.total === 0) return null;
  const first = (data.page - 1) * data.page_size + 1;
  const last = Math.min(data.page * data.page_size, data.total);

  return (
    <nav aria-label="Pagination" className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-zinc-600">
      <span className="inline-flex items-center gap-2">
        {first}–{last} of {data.total}
        {fetching && <Spinner />}
      </span>
      {data.pages > 1 && (
        <div className="flex items-center gap-2">
          <Button disabled={fetching || data.page <= 1} onClick={() => onPage(data.page - 1)}>
            Previous
          </Button>
          <span>
            Page {data.page} of {data.pages}
          </span>
          <Button disabled={fetching || data.page >= data.pages} onClick={() => onPage(data.page + 1)}>
            Next
          </Button>
        </div>
      )}
    </nav>
  );
}

/** What to show in place of the list: a first-use message, or "no matches" when a search is active. */
export function emptyMessage(searching: boolean, whenEmpty: string): string {
  return searching ? "Nothing matches your search." : whenEmpty;
}
