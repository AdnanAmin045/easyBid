"use client";

import { useState } from "react";
import { Badge, Button, Card, Field, Input, Notice, PageHeader, Select, Textarea } from "@/components/ui";
import { Pagination, SearchInput } from "@/components/list";
import { api, useApi, usePaged, type Project, type Prompt, type PromptKind, type PromptTest } from "@/lib/api";

const KINDS: Record<PromptKind, { label: string; help: string; placeholder: string }> = {
  proposal: {
    label: "Proposal prompt",
    help: "Tells the AI how to write your proposals: tone, structure, what to mention and what to avoid. Required.",
    placeholder:
      "Example: Write in first person as a full-stack developer. Open with the client's actual problem, not a greeting. Mention one relevant past project from my profile. End with one specific question about the job. Friendly, direct, no buzzwords.",
  },
  selection: {
    label: "Selection prompt",
    help: "Tells the AI which projects to bid on and which to skip. Optional: without it, every project that passes the rules in Settings gets a proposal.",
    placeholder:
      "Example: Bid only on React, Next.js, Node.js and AI integration work that one developer can finish. Skip WordPress, data entry, academic work and anything asking for free samples.",
  },
};

function Editor({ kind, current }: { kind: PromptKind; current: Prompt | null }) {
  const [filters] = useState({ kind });
  const versions = usePaged<Prompt>("/prompts", { pageSize: 5, filters });
  const found = usePaged<Project>("/projects", { pageSize: 30 });
  const prompts = versions.data?.items ?? [];
  const projects = found.data?.items ?? [];
  const onSaved = versions.reload;
  const [content, setContent] = useState(current?.content ?? "");
  const [note, setNote] = useState("");
  const [projectId, setProjectId] = useState("");
  const [result, setResult] = useState<PromptTest | null>(null);
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
      const prompt = await api<Prompt>("/prompts", { method: "POST", body: { kind, content, note, activate: true } });
      setNote("");
      setSaved(`Saved as version ${prompt.version} and made active.`);
      onSaved();
    });

  const test = () =>
    run("test", async () => {
      setResult(null);
      setResult(await api<PromptTest>("/prompts/test", { method: "POST", body: { kind, content, project_id: Number(projectId) } }));
    });

  const setActive = (prompt: Prompt, on: boolean) =>
    run("activate", async () => {
      await api(`/prompts/${prompt.id}/activate?active=${on}`, { method: "POST" });
      onSaved();
    });

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-6 lg:col-span-2">
        <Card title={KINDS[kind].label}>
          <p className="mb-3 text-sm text-zinc-500">{KINDS[kind].help}</p>
          <Notice>{error}</Notice>
          <Notice tone="green">{saved}</Notice>
          <Textarea rows={14} value={content} placeholder={KINDS[kind].placeholder} onChange={(e) => setContent(e.target.value)} />
          <p className="mt-2 text-xs text-zinc-500">
            The job details and your profile are attached to every request automatically, so the prompt only needs your instructions.
          </p>
          <div className="mt-4 flex flex-wrap items-end gap-3">
            <div className="min-w-48 flex-1">
              <Field label="Note for this version (optional)">
                <Input value={note} maxLength={300} placeholder="What changed" onChange={(e) => setNote(e.target.value)} />
              </Field>
            </div>
            <Button variant="primary" disabled={Boolean(busy) || !content.trim()} onClick={save}>
              {busy === "save" ? "Saving…" : "Save as new version"}
            </Button>
          </div>
        </Card>

        <Card title="Test on a real project">
          <p className="mb-3 text-sm text-zinc-500">Runs the text in the editor, saved or not. A test never sends a bid.</p>
          <div className="flex flex-wrap gap-3">
            <SearchInput onSearch={found.search} placeholder="Search projects" />
            <div className="min-w-48 flex-1">
              <Select aria-label="Project" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
                <option value="">{projects.length ? "Choose a project" : "No projects found"}</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title}
                  </option>
                ))}
              </Select>
            </div>
            <Button disabled={Boolean(busy) || !projectId || !content.trim()} onClick={test}>
              {busy === "test" ? "Running…" : "Test"}
            </Button>
          </div>
          {result && kind === "selection" && (
            <div className="mt-4 rounded-md bg-zinc-50 p-3 text-sm">
              <Badge tone={result.apply ? "green" : "gray"}>{result.apply ? "bid" : "skip"}</Badge>
              <p className="mt-2 text-zinc-700">{result.reason}</p>
            </div>
          )}
          {result && kind === "proposal" && (
            <div className="mt-4 rounded-md bg-zinc-50 p-3 text-sm">
              <p className="whitespace-pre-wrap text-zinc-800">{result.text}</p>
              <p className="mt-3 text-xs text-zinc-500">
                {result.chars} characters · bid {result.amount} · period {result.period}
              </p>
            </div>
          )}
        </Card>
      </div>

      <Card title="Versions">
        <div className="mb-3">
          <SearchInput onSearch={versions.search} placeholder="Search versions" />
        </div>
        {versions.data?.total === 0 && (
          <p className="text-sm text-zinc-500">{versions.q ? "Nothing matches your search." : "No versions saved yet."}</p>
        )}
        <ul className="space-y-3">
          {prompts.map((prompt) => (
            <li key={prompt.id} className="rounded-md border border-zinc-200 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">v{prompt.version}</span>
                {prompt.is_active && <Badge tone="green">active</Badge>}
              </div>
              <p className="mt-1 text-xs text-zinc-500">
                {new Date(prompt.created_at).toLocaleDateString()}
                {prompt.note && ` · ${prompt.note}`}
              </p>
              <p className="mt-2 line-clamp-3 text-xs text-zinc-600">{prompt.content}</p>
              <div className="mt-2 flex gap-3 text-xs font-medium text-indigo-700">
                <button type="button" onClick={() => setContent(prompt.content)}>
                  Load into editor
                </button>
                {!prompt.is_active && (
                  <button type="button" disabled={Boolean(busy)} onClick={() => setActive(prompt, true)}>
                    Make active
                  </button>
                )}
                {prompt.is_active && kind === "selection" && (
                  <button type="button" disabled={Boolean(busy)} onClick={() => setActive(prompt, false)}>
                    Turn off
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
        <Pagination data={versions.data} onPage={versions.setPage} />
      </Card>
    </div>
  );
}

export default function PromptsPage() {
  const [kind, setKind] = useState<PromptKind>("proposal");
  const { data: current, error, loading } = useApi<Prompt | null>(`/prompts/current?kind=${kind}`);

  return (
    <>
      <PageHeader title="Prompts" subtitle="Your instructions to the AI. Every save is kept as a version." />
      <div className="mb-6 inline-flex rounded-md border border-zinc-300 bg-white p-1">
        {(Object.keys(KINDS) as PromptKind[]).map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setKind(k)}
            className={`rounded px-3 py-1.5 text-sm font-medium ${kind === k ? "bg-indigo-600 text-white" : "text-zinc-600"}`}
          >
            {KINDS[k].label}
          </button>
        ))}
      </div>
      <Notice>{error}</Notice>
      {/* The key resets the editor when switching tabs. */}
      {!loading && !error && <Editor key={kind} kind={kind} current={current ?? null} />}
    </>
  );
}
