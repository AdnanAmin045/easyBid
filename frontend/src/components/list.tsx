"use client";

import { useEffect, useState } from "react";
import { Button, Input } from "@/components/ui";
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

export function Pagination<T>({ data, onPage }: { data: Page<T> | undefined; onPage: (page: number) => void }) {
  if (!data || data.total === 0) return null;
  const first = (data.page - 1) * data.page_size + 1;
  const last = Math.min(data.page * data.page_size, data.total);

  return (
    <nav aria-label="Pagination" className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-zinc-600">
      <span>
        {first}–{last} of {data.total}
      </span>
      {data.pages > 1 && (
        <div className="flex items-center gap-2">
          <Button disabled={data.page <= 1} onClick={() => onPage(data.page - 1)}>
            Previous
          </Button>
          <span>
            Page {data.page} of {data.pages}
          </span>
          <Button disabled={data.page >= data.pages} onClick={() => onPage(data.page + 1)}>
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
