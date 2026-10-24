"use client";

import { useState } from "react";
import { Badge, Button, Card, Empty, Field, Input, Loading, Notice, PageHeader, Textarea } from "@/components/ui";
import { api, timeAgo, useApi, type OutreachTemplate } from "@/lib/api";

const BLANK = { name: "", subject: "", body: "" };

function Editor({ initial, onSaved, onCancel }: { initial: { id?: number; name: string; subject: string; body: string }; onSaved: () => void; onCancel: () => void }) {
  const [t, setT] = useState(initial);
  const [brief, setBrief] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function save() {
    setBusy("save");
    setError("");
    try {
      await api(t.id ? `/outreach/templates/${t.id}` : "/outreach/templates", { method: t.id ? "PUT" : "POST", body: { name: t.name, subject: t.subject, body: t.body } });
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy("");
  }

  async function write() {
    if ((t.subject || t.body) && !confirm("Replace the current subject and message?")) return;
    setBusy("write");
    setError("");
    try {
      const r = await api<{ subject: string; body: string }>("/outreach/templates/generate", { method: "POST", body: { brief } });
      setT({ ...t, subject: r.subject, body: r.body });
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy("");
  }

  return (
    <Card title={t.id ? "Edit template" : "New template"}>
      <Notice>{error}</Notice>
      <div className="space-y-4">
        <Field label="Name">
          <Input value={t.name} maxLength={160} onChange={(e) => setT({ ...t, name: e.target.value })} />
        </Field>
        <div className="flex flex-wrap items-end gap-2 rounded-[10px] border border-brand-200 bg-brand-50/40 p-3">
          <div className="min-w-60 flex-1">
            <Field label="Describe the email and let the AI write it">
              <Input value={brief} maxLength={4000} onChange={(e) => setBrief(e.target.value)} placeholder="Offer SEO audits to local dentists and ask for a call" />
            </Field>
          </div>
          <Button variant="dark" loading={busy === "write"} disabled={Boolean(busy) || brief.trim().length < 10} onClick={write}>
            Write
          </Button>
        </div>
        <Field label="Subject">
          <Input value={t.subject} maxLength={300} onChange={(e) => setT({ ...t, subject: e.target.value })} />
        </Field>
        <Field label="Message" hint="Use {{first_name|there}} for details of each person and {Hi|Hello} for wording options.">
          <Textarea rows={12} value={t.body} onChange={(e) => setT({ ...t, body: e.target.value })} />
        </Field>
      </div>
      <div className="mt-5 flex gap-2 border-t border-stone-200 pt-4">
        <Button variant="primary" loading={busy === "save"} disabled={Boolean(busy) || !t.name.trim() || !t.subject.trim() || !t.body.trim()} onClick={save}>
          Save template
        </Button>
        <Button disabled={Boolean(busy)} onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </Card>
  );
}

export default function TemplatesPage() {
  const { data, error, loading, reload } = useApi<OutreachTemplate[]>("/outreach/templates");
  const [editing, setEditing] = useState<{ id?: number; name: string; subject: string; body: string } | null>(null);
  const [actionError, setActionError] = useState("");

  async function remove(t: OutreachTemplate) {
    if (!confirm(`Delete the template "${t.name}"? Campaigns that used it keep their own copy.`)) return;
    setActionError("");
    try {
      await api(`/outreach/templates/${t.id}`, { method: "DELETE" });
      reload();
    } catch (e) {
      setActionError((e as Error).message);
    }
  }

  return (
    <>
      <PageHeader
        title="Templates"
        subtitle="Emails you reuse. Pick one when you set up a campaign; the campaign keeps its own copy."
        action={!editing && <Button variant="primary" onClick={() => setEditing(BLANK)}>New template</Button>}
      />
      <Notice>{error || actionError}</Notice>
      {editing && (
        <div className="mb-6">
          <Editor
            key={editing.id ?? "new"}
            initial={editing}
            onCancel={() => setEditing(null)}
            onSaved={() => {
              setEditing(null);
              reload();
            }}
          />
        </div>
      )}
      {loading ? (
        <Loading />
      ) : data?.length === 0 ? (
        !editing && <Empty>No templates yet. Save one from a campaign, or write it here.</Empty>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {data?.map((t) => (
            <Card key={t.id} title={t.name} action={<Badge tone="gray">{timeAgo(t.updated_at)}</Badge>}>
              <p className="truncate text-sm font-medium text-stone-900">{t.subject}</p>
              <p className="mt-2 line-clamp-5 whitespace-pre-wrap text-sm text-stone-600">{t.body}</p>
              <div className="mt-4 flex gap-2">
                <Button onClick={() => setEditing(t)}>Edit</Button>
                <Button variant="danger" onClick={() => remove(t)}>
                  Delete
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
