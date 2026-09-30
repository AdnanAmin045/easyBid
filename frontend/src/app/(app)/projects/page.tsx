"use client";

import { useState } from "react";
import { Badge, Button, Empty, Notice, PageHeader, Select } from "@/components/ui";
import { api, budgetLabel, timeAgo, useApi, type Project, type Settings } from "@/lib/api";

const STATUSES = ["", "proposed", "filtered", "skipped", "error", "new"];

export default function ProjectsPage() {
  const [status, setStatus] = useState("");
  const { data, error, reload } = useApi<Project[]>(`/projects?limit=100${status ? `&status=${status}` : ""}`);
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
        subtitle="Every project EasyBid has seen, and why it was taken or left."
        action={
          <div className="w-44">
            <Select value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s || "All statuses"}
                </option>
              ))}
            </Select>
          </div>
        }
      />
      <Notice>{error || actionError}</Notice>
      {data?.length === 0 && <Empty>No projects yet.</Empty>}
      <div className="space-y-2">
        {data?.map((project) => (
          <div key={project.id} className="rounded-lg border border-zinc-200 bg-white p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <a href={project.url} target="_blank" rel="noreferrer" className="min-w-0 font-medium text-zinc-900 hover:text-indigo-700">
                {project.title}
              </a>
              <div className="flex items-center gap-2">
                {project.score !== null && <span className="text-xs text-zinc-500">score {project.score}</span>}
                <Badge>{project.status}</Badge>
              </div>
            </div>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-zinc-500">
              <span>{budgetLabel(project)}</span>
              <span>{project.bid_count} bids</span>
              <span>posted {timeAgo(project.submitted_at)}</span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {project.skills.map((skill, i) => (
                <span
                  key={skill}
                  className={`rounded px-1.5 py-0.5 text-xs ${
                    mine.has(project.skill_ids[i]) ? "bg-indigo-50 font-medium text-indigo-700" : "bg-zinc-100 text-zinc-500"
                  }`}
                >
                  {skill}
                </span>
              ))}
            </div>
            {project.reason && <p className="mt-2 text-sm text-zinc-600">{project.reason}</p>}
            {["filtered", "skipped", "error"].includes(project.status) && (
              <Button className="mt-3" disabled={busy !== null} onClick={() => write(project)}>
                {busy === project.id ? "Writing…" : "Write a proposal anyway"}
              </Button>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
