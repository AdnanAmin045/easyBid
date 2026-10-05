"use client";

import { useRef, useState } from "react";
import { ListBody, Pagination, SearchInput, emptyMessage } from "@/components/list";
import { Badge, Button, Card, Empty, Field, Input, Notice, PageHeader, Select, Textarea } from "@/components/ui";
import { api, download, fileSize, upload, useApi, usePaged, type JobProfileItem, type Resume } from "@/lib/api";

type Draft = Omit<JobProfileItem, "id">;

const KINDS: Record<JobProfileItem["kind"], string> = {
  summary: "Summary",
  experience: "Experience",
  project: "Project",
  skill: "Skill",
  education: "Education",
  link: "Link",
};
const EMPTY: Draft = { kind: "experience", title: "", content: "", is_active: true };

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
          <Select value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value as JobProfileItem["kind"] })}>
            {Object.entries(KINDS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
        <div className="sm:col-span-2">
          <Field label="Title">
            <Input value={draft.title} maxLength={300} placeholder="e.g. Full-stack developer at Acme, 2022 to 2024" onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
          </Field>
        </div>
      </div>
      <Field label="Details">
        <Textarea rows={3} value={draft.content} placeholder="What you did, the stack, measurable results" onChange={(e) => setDraft({ ...draft, content: e.target.value })} />
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

function Resumes() {
  const { data, error, loading, fetching, reload } = useApi<Resume[]>("/jobs/resumes");
  const input = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState("");
  const [actionError, setActionError] = useState("");

  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(label);
    setActionError("");
    try {
      await fn();
      reload();
    } catch (e) {
      setActionError((e as Error).message);
    }
    setBusy("");
  }

  function onFile(file: File | undefined) {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("name", name);
    act("upload", async () => {
      await upload("/jobs/resumes", form);
      setName("");
    });
    if (input.current) input.current.value = "";
  }

  const locked = Boolean(busy) || fetching;

  return (
    <Card title="CVs">
      <Notice>{error || actionError}</Notice>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="min-w-48 flex-1">
          <Field label="Name (optional)" hint="PDF or Word, up to 5 MB">
            <Input value={name} maxLength={120} placeholder="e.g. Full-stack CV" onChange={(e) => setName(e.target.value)} />
          </Field>
        </div>
        <input ref={input} type="file" accept=".pdf,.docx,application/pdf" className="hidden" onChange={(e) => onFile(e.target.files?.[0])} />
        <Button variant="dark" loading={busy === "upload"} disabled={locked} onClick={() => input.current?.click()}>
          {busy === "upload" ? "Uploading…" : "Upload CV"}
        </Button>
      </div>
      {loading ? (
        <p className="text-sm text-stone-500">Loading…</p>
      ) : data?.length === 0 ? (
        <Empty>No CV yet. Upload one to attach it to applications.</Empty>
      ) : (
        <ul className="divide-y divide-stone-200 rounded-[6px] border border-stone-200">
          {data?.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
              <span className="grid h-8 w-8 place-items-center rounded-[4px] bg-stone-100 font-mono text-[10px] font-medium uppercase text-stone-600">
                {r.filename.split(".").pop()}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium text-stone-900">{r.name}</span>
                  {r.is_default && <Badge tone="brand">default</Badge>}
                </div>
                <div className="truncate font-mono text-[11px] text-stone-500">
                  {r.filename} · {fileSize(r.size)}
                </div>
              </div>
              <div className="flex gap-3 text-xs font-medium text-brand-700">
                <button type="button" className="disabled:opacity-50" disabled={locked} onClick={() => act(`download-${r.id}`, () => download(`/jobs/resumes/${r.id}/file`, r.filename))}>
                  {busy === `download-${r.id}` ? "Downloading…" : "Download"}
                </button>
                {!r.is_default && (
                  <button type="button" className="disabled:opacity-50" disabled={locked} onClick={() => act(`default-${r.id}`, () => api(`/jobs/resumes/${r.id}/default`, { method: "POST" }))}>
                    {busy === `default-${r.id}` ? "Saving…" : "Make default"}
                  </button>
                )}
                <button
                  type="button"
                  className="text-red-700 disabled:opacity-50"
                  disabled={locked}
                  onClick={() => confirm(`Delete "${r.name}"?`) && act(`delete-${r.id}`, () => api(`/jobs/resumes/${r.id}`, { method: "DELETE" }))}
                >
                  {busy === `delete-${r.id}` ? "Deleting…" : "Delete"}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export default function JobProfilePage() {
  const [kind, setKind] = useState("");
  const { data, error, loading, fetching, reload, setPage, q, search } = usePaged<JobProfileItem>("/jobs/profile", { filters: { kind } });
  const [editing, setEditing] = useState<number | null>(null);
  const [busy, setBusy] = useState("");
  const [actionError, setActionError] = useState("");

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
      <PageHeader title="Profile & CVs" subtitle="What the AI may say about you in applications, and the files it can attach. Nothing outside this page is claimed." />

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-6">
          <Card title="Add to your profile">
            <ItemForm
              initial={EMPTY}
              submitLabel="Add"
              onSubmit={async (draft) => {
                await api("/jobs/profile", { method: "POST", body: draft });
                reload();
              }}
            />
          </Card>

          <div>
            <Notice>{error || actionError}</Notice>
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
              {data?.total === 0 && <Empty>{emptyMessage(Boolean(q || kind), "Nothing yet. Add a summary and your recent roles to start.")}</Empty>}
              <div className="space-y-2">
                {data?.items.map((item) => (
                  <div key={item.id} className="rounded-[8px] border border-stone-300/70 bg-white p-4">
                    {editing === item.id ? (
                      <ItemForm
                        initial={item}
                        submitLabel="Save"
                        onCancel={() => setEditing(null)}
                        onSubmit={async (draft) => {
                          await api(`/jobs/profile/${item.id}`, { method: "PUT", body: draft });
                          setEditing(null);
                          reload();
                        }}
                      />
                    ) : (
                      <>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex min-w-0 items-center gap-2">
                            <Badge tone="gray">{KINDS[item.kind]}</Badge>
                            <span className={`truncate font-medium ${item.is_active ? "text-stone-900" : "text-stone-400 line-through"}`}>{item.title}</span>
                          </div>
                          <div className="flex gap-3 text-xs font-medium text-brand-700">
                            <button type="button" className="disabled:opacity-50" disabled={locked} onClick={() => setEditing(item.id)}>
                              Edit
                            </button>
                            <button
                              type="button"
                              className="disabled:opacity-50"
                              disabled={locked}
                              onClick={() => act(`toggle-${item.id}`, () => api(`/jobs/profile/${item.id}`, { method: "PUT", body: { ...item, is_active: !item.is_active } }))}
                            >
                              {busy === `toggle-${item.id}` ? "Saving…" : item.is_active ? "Turn off" : "Turn on"}
                            </button>
                            <button
                              type="button"
                              className="text-red-700 disabled:opacity-50"
                              disabled={locked}
                              onClick={() => confirm(`Delete "${item.title}"?`) && act(`delete-${item.id}`, () => api(`/jobs/profile/${item.id}`, { method: "DELETE" }))}
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
          </div>
        </div>

        <div>
          <Resumes />
        </div>
      </div>
    </>
  );
}
