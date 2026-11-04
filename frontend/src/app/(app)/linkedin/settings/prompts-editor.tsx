"use client";

import { useState } from "react";
import { Button, Card, Field, Input, Textarea } from "@/components/ui";
import type { LinkedInDefaults, LinkedInPillar, LinkedInPrompts, LinkedInSettings, LinkedInTarget } from "@/lib/api";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

type TextKey = "writer_style" | "planner_guidance" | "poster_guidance";

const TEXTS: { key: TextKey; label: string; hint: string; rows: number }[] = [
  {
    key: "writer_style",
    label: "How a post must read",
    hint: "Hook, length, paragraphs, how it ends, words to avoid. Followed by the writer for every post.",
    rows: 10,
  },
  {
    key: "planner_guidance",
    label: "How the best topic is chosen",
    hint: "What a good idea must be. The planner proposes ideas by these rules and the first one is written.",
    rows: 8,
  },
  {
    key: "poster_guidance",
    label: "How posters are decided",
    hint: "When a poster is used and which layout fits which idea.",
    rows: 9,
  },
];

export function PromptsEditor({ s, setS, defaults }: { s: LinkedInSettings; setS: (s: LinkedInSettings) => void; defaults: LinkedInDefaults }) {
  const [week, setWeek] = useState<LinkedInTarget>("personal");
  const p = s.prompts;
  const set = (patch: Partial<LinkedInPrompts>) => setS({ ...s, prompts: { ...p, ...patch } });

  // A blank setting means the recommended text; the box shows what is actually in force.
  const shown = (key: TextKey) => p[key] || defaults.prompts[key];
  const edit = (key: TextKey, value: string) => set({ [key]: value.trim() === defaults.prompts[key].trim() ? "" : value } as Partial<LinkedInPrompts>);

  const pillarKey = week === "personal" ? "personal_pillars" : "company_pillars";
  const rows: LinkedInPillar[] = p[pillarKey].length === 7 ? p[pillarKey] : defaults.prompts.pillars[week];
  const customWeek = p[pillarKey].length === 7;
  const editRow = (i: number, patch: Partial<LinkedInPillar>) => set({ [pillarKey]: rows.map((r, j) => (j === i ? { ...r, ...patch } : r)) } as Partial<LinkedInPrompts>);

  return (
    <Card title="How posts are written (advanced)">
      <p className="mb-4 text-sm text-stone-500">
        These are the instructions the topic planner and the writer follow. They start as the recommended text; change anything you like, or reset it. The truth
        rules at the bottom are always applied and cannot be changed.
      </p>
      <div className="space-y-5">
        {TEXTS.map((t) => (
          <Field key={t.key} label={t.label} hint={t.hint}>
            <Textarea rows={t.rows} value={shown(t.key)} maxLength={6000} onChange={(e) => edit(t.key, e.target.value)} className="font-mono text-xs leading-relaxed" />
            <div className="mt-1.5 flex items-center gap-3 text-xs text-stone-500">
              <span>{p[t.key] ? "Changed from the recommended text." : "Recommended text."}</span>
              {p[t.key] && (
                <button type="button" onClick={() => set({ [t.key]: "" } as Partial<LinkedInPrompts>)} className="font-medium text-brand-700 underline">
                  Reset to recommended
                </button>
              )}
            </div>
          </Field>
        ))}

        <div>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-medium text-stone-800">The week&apos;s plan: what each day&apos;s post is about</div>
              <div className="text-xs text-stone-500">One kind of post per weekday, so the feed has a rhythm and does not repeat itself.</div>
            </div>
            <div className="flex gap-1.5">
              {(["personal", "company"] as LinkedInTarget[]).map((t) => (
                <Button key={t} variant={week === t ? "primary" : "secondary"} onClick={() => setWeek(t)}>
                  {t === "personal" ? "Personal profile" : "Company page"}
                </Button>
              ))}
            </div>
          </div>
          <div className="space-y-2">
            {rows.map((r, i) => (
              <div key={`${week}-${i}`} className="grid gap-2 md:grid-cols-[7rem_10rem_1fr] md:items-start">
                <div className="pt-2 text-sm font-medium text-stone-600">{DAYS[i]}</div>
                <Input value={r.name} maxLength={40} onChange={(e) => editRow(i, { name: e.target.value })} aria-label={`${DAYS[i]} post type`} />
                <Textarea rows={3} value={r.instruction} maxLength={800} onChange={(e) => editRow(i, { instruction: e.target.value })} className="text-xs" aria-label={`${DAYS[i]} instruction`} />
              </div>
            ))}
          </div>
          <div className="mt-2 flex items-center gap-3 text-xs text-stone-500">
            <span>{customWeek ? "Changed from the recommended week." : "Recommended week."}</span>
            {customWeek && (
              <button type="button" onClick={() => set({ [pillarKey]: [] } as Partial<LinkedInPrompts>)} className="font-medium text-brand-700 underline">
                Reset this week
              </button>
            )}
          </div>
        </div>

        <details className="rounded-[12px] border border-stone-200 bg-stone-50 px-4 py-3">
          <summary className="cursor-pointer text-sm font-medium text-stone-800">Truth rules (always applied, cannot be changed)</summary>
          <pre className="mt-3 whitespace-pre-wrap text-xs leading-relaxed text-stone-700">{defaults.prompts.locked_rules}</pre>
          <p className="mt-2 text-xs text-stone-500">
            The same rules are also checked in code after a post is written: a number, a statistic or a story that is not in the research, your profile or the website
            sends the post back to be rewritten.
          </p>
        </details>
      </div>
    </Card>
  );
}
