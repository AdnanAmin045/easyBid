"use client";

import { useState } from "react";
import { Badge, Button, Empty, Notice, PageHeader, Select } from "@/components/ui";
import { ListBody, Pagination, SearchInput, emptyMessage } from "@/components/list";
import { api, budgetLabel, timeAgo, useApi, usePaged, type Project, type Settings } from "@/lib/api";

const STATUSES = ["", "proposed", "filtered", "skipped", "error", "new"];

export default function ProjectsPage() {
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const { data, error, loading, fetching, reload, setPage, q, search } = usePaged<Project>("/projects", { filters: { status, type } });
  const { data: settings } = useApi<Settings>("/settings");
  const mine = new Set(settings?.skill_ids ?? []);
  const [busy, setBusy] = useState<number | null>(null);
  const [actionError, setActionError] = useState("");

  async function write(project: Project) {
    setBusy(project.id);
    setActionError("");
    try {
      await api(`/projects/${project.id}/generate`, { method: "POST" });
      reload();
    } catch (e) {
      setActionError((e as Error).message);
    }
    setBusy(null);
  }

  return (
    <>
      <PageHeader
        title="Projects"
        subtitle="Every Freelancer.com project seen, and why it was taken or left."
        action={
          <div className="flex flex-wrap gap-2">
            <SearchInput onSearch={search} placeholder="Search title, description, skills" />
            <div className="w-40">
              <Select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s || "All statuses"}
                  </option>
                ))}
              </Select>
            </div>
            <div className="w-32">
              <Select aria-label="Type" value={type} onChange={(e) => setType(e.target.value)}>
                <option value="">All types</option>
                <option value="fixed">Fixed</option>
                <option value="hourly">Hourly</option>
              </Select>
            </div>
          </div>
        }
      />
      <Notice>{error || actionError}</Notice>
      <ListBody loading={loading} fetching={fetching}>
        {data?.total === 0 && <Empty>{emptyMessage(Boolean(q || status || type), "No projects yet.")}</Empty>}
        <div className="space-y-2">
          {data?.items.map((project) => (
            <div key={project.id} className="rounded-lg border border-stone-200 bg-white p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <a href={project.url} target="_blank" rel="noreferrer" className="min-w-0 font-medium text-stone-900 hover:text-brand-700">
                  {project.title}
                </a>
                <div className="flex items-center gap-2">
                  {project.score !== null && <span className="text-xs text-stone-500">score {project.score}</span>}
                  <Badge>{project.status}</Badge>
                </div>
              </div>
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-stone-500">
                <span>{budgetLabel(project)}</span>
                <span>{project.bid_count} bids</span>
                <span>posted {timeAgo(project.submitted_at)}</span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {project.skills.map((skill, i) => (
                  <span
                    key={skill}
                    className={`rounded px-1.5 py-0.5 text-xs ${
                      mine.has(project.skill_ids[i]) ? "bg-brand-50 font-medium text-brand-700" : "bg-stone-100 text-stone-500"
                    }`}
                  >
                    {skill}
                  </span>
                ))}
              </div>
              {project.reason && <p className="mt-2 text-sm text-stone-600">{project.reason}</p>}
              {["filtered", "skipped", "error"].includes(project.status) && (
                <Button className="mt-3" loading={busy === project.id} disabled={busy !== null || fetching} onClick={() => write(project)}>
                  {busy === project.id ? "Writing…" : "Write a proposal anyway"}
                </Button>
              )}
            </div>
          ))}
        </div>
      </ListBody>
      <Pagination data={data} fetching={fetching} onPage={setPage} />
    </>
  );
}
