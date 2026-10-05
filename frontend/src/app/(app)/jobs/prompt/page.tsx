"use client";

import { useState } from "react";
import { ListBody, Pagination } from "@/components/list";
import { Badge, Button, Card, Field, Input, Loading, Notice, PageHeader, Textarea } from "@/components/ui";
import { api, useApi, usePaged, type Prompt } from "@/lib/api";

interface Current {
  content: string;
  version: number | null;
  builtin: boolean;
}

function Editor({ current }: { current: Current }) {
  const versions = usePaged<Prompt>("/jobs/prompts", { pageSize: 6 });
  const [content, setContent] = useState(current.content);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");

  async function run(name: string, fn: () => Promise<void>) {
    setBusy(name);
    setError("");
    setSaved("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy("");
  }

  const save = () =>
    run("save", async () => {
      const prompt = await api<Prompt>("/jobs/prompts", { method: "POST", body: { content, note } });
      setNote("");
      setSaved(`Saved as version ${prompt.version} and made active.`);
      versions.reload();
    });

  const activate = (prompt: Prompt) =>
    run(`activate-${prompt.id}`, async () => {
      await api(`/jobs/prompts/${prompt.id}/activate`, { method: "POST" });
      setContent(prompt.content);
      versions.reload();
    });

  return (
    <div className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
      <Card title={current.builtin ? "Writing prompt · built-in" : `Writing prompt · v${current.version}`}>
        <p className="mb-3 text-sm text-stone-500">
          How the AI writes your applications: tone, structure, what to stress. The job description, your profile and the application instructions
          are added to every request automatically.
        </p>
        <Notice>{error}</Notice>
        <Notice tone="green">{saved}</Notice>
        <Textarea rows={16} value={content} onChange={(e) => setContent(e.target.value)} />
        <div className="mt-4 flex flex-wrap items-end gap-3">
          <div className="min-w-48 flex-1">
            <Field label="Note for this version (optional)">
              <Input value={note} maxLength={300} placeholder="What changed" onChange={(e) => setNote(e.target.value)} />
            </Field>
          </div>
          <Button variant="primary" loading={busy === "save"} disabled={Boolean(busy) || !content.trim()} onClick={save}>
            {busy === "save" ? "Saving…" : "Save as new version"}
          </Button>
        </div>
      </Card>

      <Card title="Versions">
        <ListBody loading={versions.loading} fetching={versions.fetching} rows={3}>
          {versions.data?.total === 0 && <p className="text-sm text-stone-500">No saved versions. The built-in prompt is in use.</p>}
          <ul className="space-y-3">
            {versions.data?.items.map((prompt) => (
              <li key={prompt.id} className="rounded-[6px] border border-stone-200 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs font-medium">v{prompt.version}</span>
                  {prompt.is_active && <Badge tone="green">active</Badge>}
                </div>
                <p className="mt-1 text-xs text-stone-500">
                  {new Date(prompt.created_at).toLocaleDateString()}
                  {prompt.note && ` · ${prompt.note}`}
                </p>
                <p className="mt-2 line-clamp-3 text-xs text-stone-600">{prompt.content}</p>
                <div className="mt-2 flex gap-3 text-xs font-medium text-brand-700">
                  <button type="button" onClick={() => setContent(prompt.content)}>
                    Load into editor
                  </button>
                  {!prompt.is_active && (
                    <button type="button" className="disabled:opacity-50" disabled={Boolean(busy)} onClick={() => activate(prompt)}>
                      {busy === `activate-${prompt.id}` ? "Saving…" : "Make active"}
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </ListBody>
        <Pagination data={versions.data} fetching={versions.fetching} onPage={versions.setPage} />
      </Card>
    </div>
  );
}

export default function JobPromptPage() {
  const { data, error } = useApi<Current>("/jobs/prompts/current");
  return (
    <>
      <PageHeader title="Writing prompt" subtitle="Your instructions to the AI for application emails. Every save is kept as a version." />
      <Notice>{error}</Notice>
      {!data && !error && <Loading label="Loading prompt…" />}
      {data && <Editor current={data} />}
    </>
  );
}
