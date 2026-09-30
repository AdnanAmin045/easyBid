"use client";

import { useState } from "react";
import { Badge, Button, Card, Empty, Field, Input, Notice, PageHeader, Select, Textarea } from "@/components/ui";
import { Pagination, SearchInput, emptyMessage } from "@/components/list";
import { api, usePaged, type ProfileItem } from "@/lib/api";

type Draft = Omit<ProfileItem, "id">;

const KINDS: Record<ProfileItem["kind"], string> = {
  bio: "About me",
  project: "Past project",
  skill: "Skill",
  link: "Link",
};
const EMPTY: Draft = { kind: "project", title: "", content: "", is_active: true };

function ItemForm({ initial, submitLabel, onSubmit, onCancel }: { initial: Draft; submitLabel: string; onSubmit: (d: Draft) => Promise<void>; onCancel?: () => void }) {
  const [draft, setDraft] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setBusy(true);
    setError("");
    try {
      await onSubmit(draft);
      if (!onCancel) setDraft(EMPTY);
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  }

  return (
    <div className="space-y-3">
      <Notice>{error}</Notice>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Type">
          <Select value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value as ProfileItem["kind"] })}>
            {Object.entries(KINDS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
        <div className="sm:col-span-2">
          <Field label="Title">
            <Input value={draft.title} maxLength={300} placeholder="e.g. Inventory dashboard for a logistics company" onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
          </Field>
        </div>
      </div>
      <Field label="Details">
        <Textarea rows={3} value={draft.content} placeholder="What you built, the stack, the result, a link" onChange={(e) => setDraft({ ...draft, content: e.target.value })} />
      </Field>
      <div className="flex gap-2">
        <Button variant="primary" disabled={busy || !draft.title.trim()} onClick={submit}>
          {submitLabel}
        </Button>
        {onCancel && <Button onClick={onCancel}>Cancel</Button>}
      </div>
    </div>
  );
}

export default function ProfilePage() {
  const [kind, setKind] = useState("");
  const { data, error, reload, setPage, q, search } = usePaged<ProfileItem>("/profile", { filters: { kind } });
  const [editing, setEditing] = useState<number | null>(null);
  const [actionError, setActionError] = useState("");

  async function act(fn: () => Promise<unknown>) {
    setActionError("");
    try {
      await fn();
      reload();
    } catch (e) {
      setActionError((e as Error).message);
    }
  }

  return (
    <>
      <PageHeader title="Profile" subtitle="What the AI knows about you. Proposals only claim experience listed here." />
      <Notice>{error || actionError}</Notice>

      <Card title="Add an item" className="mb-6">
        <ItemForm
          initial={EMPTY}
          submitLabel="Add"
          onSubmit={async (draft) => {
            await api("/profile", { method: "POST", body: draft });
            reload();
          }}
        />
      </Card>

      <div className="mb-3 flex flex-wrap gap-2">
        <SearchInput onSearch={search} placeholder="Search your profile" />
        <div className="w-40">
          <Select aria-label="Type" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">All types</option>
            {Object.entries(KINDS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>
      </div>
      {data?.total === 0 && (
        <Empty>{emptyMessage(Boolean(q || kind), "Nothing here yet. Add your bio and two or three past projects to start.")}</Empty>
      )}
      <div className="space-y-2">
        {data?.items.map((item) => (
          <div key={item.id} className="rounded-lg border border-zinc-200 bg-white p-4">
            {editing === item.id ? (
              <ItemForm
                initial={item}
                submitLabel="Save"
                onCancel={() => setEditing(null)}
                onSubmit={async (draft) => {
                  await api(`/profile/${item.id}`, { method: "PUT", body: draft });
                  setEditing(null);
                  reload();
                }}
              />
            ) : (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Badge tone="blue">{KINDS[item.kind]}</Badge>
                    <span className={`font-medium ${item.is_active ? "text-zinc-900" : "text-zinc-400 line-through"}`}>{item.title}</span>
                  </div>
                  <div className="flex gap-3 text-xs font-medium text-indigo-700">
                    <button type="button" onClick={() => setEditing(item.id)}>
                      Edit
                    </button>
                    <button type="button" onClick={() => act(() => api(`/profile/${item.id}`, { method: "PUT", body: { ...item, is_active: !item.is_active } }))}>
                      {item.is_active ? "Turn off" : "Turn on"}
                    </button>
                    <button type="button" className="text-red-700" onClick={() => confirm(`Delete "${item.title}"?`) && act(() => api(`/profile/${item.id}`, { method: "DELETE" }))}>
                      Delete
                    </button>
                  </div>
                </div>
                {item.content && <p className="mt-2 whitespace-pre-wrap text-sm text-zinc-600">{item.content}</p>}
              </>
            )}
          </div>
        ))}
      </div>
      <Pagination data={data} onPage={setPage} />
    </>
  );
}
