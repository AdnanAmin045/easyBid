"use client";

import Link from "next/link";
import { useState } from "react";
import { Progress } from "@/components/campaign-progress";
import { ListBody, Pagination, SearchInput, emptyMessage } from "@/components/list";
import { Badge, Button, Empty, Notice, PageHeader, Select } from "@/components/ui";
import { download, timeAgo, usePaged, type CampaignListItem } from "@/lib/api";

const STATUSES = ["", "draft", "running", "paused", "completed", "cancelled"];

export default function CampaignsPage() {
  const [status, setStatus] = useState("");
  const { data, error, loading, fetching, setPage, q, search } = usePaged<CampaignListItem>("/outreach/campaigns", { filters: { status } });
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");
  const exportContacted = async () => {
    setExporting(true);
    setExportError("");
    try {
      await download("/outreach/contacted/export", "contacted-addresses.csv");
    } catch (e) {
      setExportError(e instanceof Error ? e.message : "Export failed.");
    } finally {
      setExporting(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Campaigns"
        subtitle="Every mailing, with how far it has got."
        action={
          <div className="flex flex-wrap gap-2">
            <SearchInput onSearch={search} placeholder="Search campaigns" />
            <div className="w-36">
              <Select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s || "All statuses"}
                  </option>
                ))}
              </Select>
            </div>
            <Button loading={exporting} onClick={exportContacted} title="Every address already written to, plus the do-not-contact list, to check new leads against">
              Export contacted
            </Button>
            <Link href="/outreach/campaigns/new">
              <Button variant="primary">New campaign</Button>
            </Link>
          </div>
        }
      />
      <Notice>{error || exportError}</Notice>
      <ListBody loading={loading} fetching={fetching}>
        {data?.total === 0 ? (
          <Empty>{emptyMessage(Boolean(q || status), "No campaigns yet. Start with New campaign.")}</Empty>
        ) : (
          <div className="overflow-x-auto rounded-[8px] border border-stone-300/70 bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-stone-200 text-left font-mono text-[10.5px] uppercase tracking-[0.12em] text-stone-500">
                  <th className="px-4 py-2.5 font-medium">Campaign</th>
                  <th className="px-4 py-2.5 font-medium">Progress</th>
                  <th className="px-4 py-2.5 font-medium">Replies</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 text-right font-medium">Created</th>
                </tr>
              </thead>
              <tbody>
                {data?.items.map((c) => (
                  <tr key={c.id} className="border-b border-stone-100 last:border-0 hover:bg-stone-50">
                    <td className="max-w-xs px-4 py-3">
                      <Link href={`/outreach/campaigns/${c.id}`} className="block truncate font-medium text-stone-900">
                        {c.name}
                      </Link>
                      <span className="block text-xs text-stone-500">{c.mode === "ai" ? "AI writes each email" : "Template"}</span>
                    </td>
                    <td className="px-4 py-3">
                      <Progress item={c} />
                    </td>
                    <td className="tabular px-4 py-3 text-stone-700">{c.counts.replied ?? 0}</td>
                    <td className="px-4 py-3">
                      <Badge>{c.status}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right font-mono text-xs text-stone-500">{timeAgo(c.created_at)}</td>
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
