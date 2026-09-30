"use client";

import { Badge, Button, Empty, Notice, PageHeader } from "@/components/ui";
import { useApi, type LogEntry } from "@/lib/api";

export default function LogsPage() {
  const { data, error, reload } = useApi<LogEntry[]>("/logs?limit=200");

  return (
    <>
      <PageHeader title="Logs" subtitle="What EasyBid did, newest first." action={<Button onClick={reload}>Refresh</Button>} />
      <Notice>{error}</Notice>
      {data?.length === 0 && <Empty>Nothing logged yet.</Empty>}
      {data && data.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white">
          <table className="w-full text-sm">
            <tbody>
              {data.map((log) => (
                <tr key={log.id} className="border-b border-zinc-100 last:border-0">
                  <td className="whitespace-nowrap px-4 py-2 text-xs text-zinc-500">{new Date(log.created_at).toLocaleString()}</td>
                  <td className="px-2 py-2">
                    <Badge tone={log.level === "error" ? "red" : "gray"}>{log.event}</Badge>
                  </td>
                  <td className="px-4 py-2 text-zinc-700">{log.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
