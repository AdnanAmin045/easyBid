"use client";

import Link from "next/link";
import { useState } from "react";
import { ListBody, Pagination, SearchInput, emptyMessage } from "@/components/list";
import { Badge, Button, Empty, Notice, PageHeader, Select } from "@/components/ui";
import { timeAgo, usePaged, type ApplicationBrief } from "@/lib/api";

const STATUSES = ["", "draft", "sent", "failed"];

export default function ApplicationsPage() {
  const [status, setStatus] = useState("");
  const { data, error, loading, fetching, setPage, q, search } = usePaged<ApplicationBrief>("/jobs/applications", {
    filters: { status },
  });

  return (
    <>
      <PageHeader
        title="Applications"
        subtitle="Every application written, with where it went and when."
        action={
          <div className="flex flex-wrap gap-2">
            <SearchInput onSearch={search} placeholder="Search company, role, email" />
            <div className="w-36">
              <Select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s || "All statuses"}
                  </option>
                ))}
              </Select>
            </div>
            <Link href="/jobs/compose">
              <Button variant="primary">New application</Button>
            </Link>
          </div>
        }
      />
      <Notice>{error}</Notice>
      <ListBody loading={loading} fetching={fetching}>
        {data?.total === 0 ? (
          <Empty>{emptyMessage(Boolean(q || status), "No applications yet. Start with New application.")}</Empty>
        ) : (
          <div className="overflow-x-auto rounded-[8px] border border-stone-300/70 bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-stone-200 text-left font-mono text-[10.5px] uppercase tracking-[0.12em] text-stone-500">
                  <th className="px-4 py-2.5 font-medium">Role</th>
                  <th className="px-4 py-2.5 font-medium">Sent to</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 text-right font-medium">When</th>
                </tr>
              </thead>
              <tbody>
                {data?.items.map((a) => (
                  <tr key={a.id} className="border-b border-stone-100 last:border-0 hover:bg-stone-50">
                    <td className="max-w-xs px-4 py-3">
                      <Link href={`/jobs/applications/${a.id}`} className="block">
                        <span className="block truncate font-medium text-stone-900">{a.role || a.subject || "Untitled role"}</span>
                        <span className="block truncate text-xs text-stone-500">{a.company || "Unknown company"}</span>
                      </Link>
                    </td>
                    <td className="max-w-[16rem] truncate px-4 py-3 text-stone-700">{a.to_email}</td>
                    <td className="px-4 py-3">
                      <Badge>{a.status}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right font-mono text-xs text-stone-500">
                      {a.sent_at ? `sent ${timeAgo(a.sent_at)}` : `created ${timeAgo(a.created_at)}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ListBody>
      <Pagination data={data} fetching={fetching} onPage={setPage} />
    </>
  );
}
