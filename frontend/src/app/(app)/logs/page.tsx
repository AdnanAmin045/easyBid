"use client";

import { useState } from "react";
import { ListBody, Pagination, SearchInput, emptyMessage } from "@/components/list";
import { Badge, Button, Empty, Notice, PageHeader, Select } from "@/components/ui";
import { usePaged, type LogEntry } from "@/lib/api";

export default function LogsPage() {
  const [level, setLevel] = useState("");
  const { data, error, loading, fetching, reload, setPage, q, search } = usePaged<LogEntry>("/logs", { pageSize: 50, filters: { level } });

  return (
    <>
      <PageHeader
        title="Logs"
        subtitle="Everything the platform did, newest first."
        action={
          <div className="flex flex-wrap gap-2">
            <SearchInput onSearch={search} placeholder="Search logs" />
            <div className="w-32">
              <Select aria-label="Level" value={level} onChange={(e) => setLevel(e.target.value)}>
                <option value="">All levels</option>
                <option value="error">Errors</option>
                <option value="info">Info</option>
              </Select>
            </div>
            <Button loading={fetching} onClick={reload}>
              Refresh
            </Button>
          </div>
        }
      />
      <Notice>{error}</Notice>
      <ListBody loading={loading} fetching={fetching} rows={6}>
        {data?.total === 0 && <Empty>{emptyMessage(Boolean(q || level), "Nothing logged yet.")}</Empty>}
        {data && data.total > 0 && (
          <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
            <table className="w-full text-sm">
              <tbody>
                {data.items.map((log) => (
                  <tr key={log.id} className="border-b border-stone-100 last:border-0">
                    <td className="whitespace-nowrap px-4 py-2 text-xs text-stone-500">{new Date(log.created_at).toLocaleString()}</td>
                    <td className="px-2 py-2">
                      <Badge tone={log.level === "error" ? "red" : "gray"}>{log.event}</Badge>
                    </td>
                    <td className="px-4 py-2 text-stone-700">{log.message}</td>
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
