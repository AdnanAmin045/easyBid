"use client";

import { useState } from "react";
import { Badge, Button, Card, Empty, Field, Input, Notice, PageHeader, Select, Textarea } from "@/components/ui";
import { ListBody, Pagination, SearchInput, emptyMessage } from "@/components/list";
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
        <Button variant="primary" loading={busy} disabled={!draft.title.trim()} onClick={submit}>
          {busy ? "Saving…" : submitLabel}
        </Button>
        {onCancel && (
          <Button disabled={busy} onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
    </div>
  );
}

export default function ProfilePage() {
  const [kind, setKind] = useState("");
  const { data, error, loading, fetching, reload, setPage, q, search } = usePaged<ProfileItem>("/profile", { filters: { kind } });
  const [editing, setEditing] = useState<number | null>(null);
  const [actionError, setActionError] = useState("");
  // The row action being saved, as "toggle-<id>" or "delete-<id>".
  const [busy, setBusy] = useState("");

  async function act(name: string, fn: () => Promise<unknown>) {
    setBusy(name);
    setActionError("");
    try {
      await fn();
      reload();
    } catch (e) {
      setActionError((e as Error).message);
    }
    setBusy("");
  }

  const locked = Boolean(busy) || fetching;

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
      <ListBody loading={loading} fetching={fetching}>
        {data?.total === 0 && (
          <Empty>{emptyMessage(Boolean(q || kind), "Nothing here yet. Add your bio and two or three past projects to start.")}</Empty>
        )}
        <div className="space-y-2">
          {data?.items.map((item) => (
            <div key={item.id} className="rounded-lg border border-stone-200 bg-white p-4">
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
                      <span className={`font-medium ${item.is_active ? "text-stone-900" : "text-stone-400 line-through"}`}>{item.title}</span>
                    </div>
                    <div className="flex gap-3 text-xs font-medium text-brand-700">
                      <button type="button" className="disabled:opacity-50" disabled={locked} onClick={() => setEditing(item.id)}>
                        Edit
                      </button>
                      <button
                        type="button"
                        className="disabled:opacity-50"
                        disabled={locked}
                        onClick={() =>
                          act(`toggle-${item.id}`, () => api(`/profile/${item.id}`, { method: "PUT", body: { ...item, is_active: !item.is_active } }))
                        }
                      >
                        {busy === `toggle-${item.id}` ? "Saving…" : item.is_active ? "Turn off" : "Turn on"}
                      </button>
                      <button
                        type="button"
                        className="text-red-700 disabled:opacity-50"
                        disabled={locked}
                        onClick={() => confirm(`Delete "${item.title}"?`) && act(`delete-${item.id}`, () => api(`/profile/${item.id}`, { method: "DELETE" }))}
                      >
                        {busy === `delete-${item.id}` ? "Deleting…" : "Delete"}
                      </button>
                    </div>
                  </div>
                  {item.content && <p className="mt-2 whitespace-pre-wrap text-sm text-stone-600">{item.content}</p>}
                </>
              )}
            </div>
          ))}
        </div>
      </ListBody>
      <Pagination data={data} fetching={fetching} onPage={setPage} />
    </>
  );
}
