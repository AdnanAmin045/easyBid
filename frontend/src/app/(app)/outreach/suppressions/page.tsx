"use client";

import { useState } from "react";
import { ListBody, Pagination, SearchInput, emptyMessage } from "@/components/list";
import { Button, Card, Empty, Field, Input, Notice, PageHeader, Textarea } from "@/components/ui";
import { api, timeAgo, usePaged, type Suppression } from "@/lib/api";

export default function SuppressionsPage() {
  const { data, error, loading, fetching, setPage, q, search, reload } = usePaged<Suppression>("/outreach/suppressions");
  const [emails, setEmails] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "red" | "green"; text: string } | null>(null);

  async function add() {
    setBusy(true);
    setMessage(null);
    try {
      const r = await api<{ added: number; already_listed: number; ignored: number }>("/outreach/suppressions", { method: "POST", body: { emails, reason } });
      setMessage({ tone: "green", text: `${r.added} added${r.already_listed ? `, ${r.already_listed} were already listed` : ""}${r.ignored ? `, ${r.ignored} lines had no address` : ""}.` });
      setEmails("");
      reload();
    } catch (e) {
      setMessage({ tone: "red", text: (e as Error).message });
    }
    setBusy(false);
  }

  async function remove(s: Suppression) {
    if (!confirm(`Allow emails to ${s.email} again?`)) return;
    try {
      await api(`/outreach/suppressions/${s.id}`, { method: "DELETE" });
      reload();
    } catch (e) {
      setMessage({ tone: "red", text: (e as Error).message });
    }
  }

  return (
    <>
      <PageHeader title="Do not contact" subtitle="Nobody on this list is ever emailed, in any campaign. Addresses that bounce are added automatically." />
      <Card title="Add addresses" className="mb-6">
        {message && <Notice tone={message.tone}>{message.text}</Notice>}
        <div className="grid gap-4 sm:grid-cols-[1fr_16rem]">
          <Field label="Addresses" hint="Paste anything with email addresses in it. Waiting emails to them are held back at once.">
            <Textarea rows={4} value={emails} onChange={(e) => setEmails(e.target.value)} />
          </Field>
          <Field label="Reason (optional)">
            <Input value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} placeholder="Asked to stop" />
          </Field>
        </div>
        <Button className="mt-3" variant="primary" loading={busy} disabled={emails.trim().length < 3} onClick={add}>
          Add to the list
        </Button>
      </Card>

      <div className="mb-3 flex justify-end">
        <SearchInput onSearch={search} placeholder="Search address or reason" />
      </div>
      <Notice>{error}</Notice>
      <ListBody loading={loading} fetching={fetching}>
        {data?.total === 0 ? (
          <Empty>{emptyMessage(Boolean(q), "Nobody on the list.")}</Empty>
        ) : (
          <div className="overflow-x-auto rounded-[8px] border border-stone-300/70 bg-white">
            <table className="w-full text-sm">
              <tbody>
                {data?.items.map((s) => (
                  <tr key={s.id} className="border-b border-stone-100 last:border-0">
                    <td className="px-4 py-2.5 font-medium text-stone-900">{s.email}</td>
                    <td className="px-4 py-2.5 text-stone-600">{s.reason || "—"}</td>
                    <td className="whitespace-nowrap px-4 py-2.5 font-mono text-xs text-stone-500">{timeAgo(s.created_at)}</td>
                    <td className="px-4 py-2.5 text-right">
                      <Button className="!px-2.5 !py-1 text-xs" onClick={() => remove(s)}>
                        Remove
                      </Button>
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
