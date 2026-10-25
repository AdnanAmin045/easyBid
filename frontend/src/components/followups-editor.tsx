"use client";

import { Button, Card, Field, Input, Textarea } from "@/components/ui";
import type { FollowUp } from "@/lib/api";

export const MAX_FOLLOWUPS = 5;

/** Wording for a new step: the first one starts a conversation again, the next ones are shorter. */
export function newFollowUp(index: number, kind: "campaign" | "job"): FollowUp {
  const body =
    kind === "job"
      ? "Hello,\n\nI wanted to follow up on my application for the {{role|open}} role at {{company|your company}}. I remain very interested and would be glad to talk whenever suits you.\n\n"
      : "{Hi|Hello} {{first_name|there}},\n\nJust following up on my last email in case it got buried.\n\n";
  return { days: index === 0 ? (kind === "job" ? 5 : 3) : 4, subject: "", body };
}

/**
 * The follow-up plan: up to five steps, each some days after the previous email, written like the first email.
 * Used for campaigns, for a single job application, and for the defaults of new applications.
 */
export function FollowUpsEditor({
  value,
  onChange,
  kind,
  title = "Follow-ups",
  variables,
}: {
  value: FollowUp[];
  onChange: (next: FollowUp[]) => void;
  kind: "campaign" | "job";
  title?: string;
  variables: string;
}) {
  return (
    <Card
      title={title}
      action={
        value.length < MAX_FOLLOWUPS && (
          <Button className="!px-2.5 !py-1 text-xs" onClick={() => onChange([...value, newFollowUp(value.length, kind)])}>
            Add a follow-up
          </Button>
        )
      }
    >
      {value.length === 0 ? (
        <p className="text-sm text-stone-500">
          No follow-ups. Add one to write again, in the same conversation, if nobody has answered after a few days. Anyone who replies or bounces is never followed up.
        </p>
      ) : (
        <div className="space-y-5">
          {value.map((f, i) => {
            const set = (patch: Partial<FollowUp>) => onChange(value.map((x, j) => (j === i ? { ...x, ...patch } : x)));
            return (
              <div key={i} className="rounded-[10px] border border-stone-200 p-4">
                <div className="mb-3 flex flex-wrap items-end gap-3">
                  <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-stone-500">Follow-up {i + 1}</span>
                  <div className="w-28">
                    <Field label={i === 0 ? "Days after the first email" : "Days after the previous one"}>
                      <Input type="number" min={1} max={60} value={String(f.days)} onChange={(e) => set({ days: Number(e.target.value) })} />
                    </Field>
                  </div>
                  <span className="flex-1" />
                  <Button variant="danger" className="!px-2.5 !py-1 text-xs" onClick={() => onChange(value.filter((_, j) => j !== i))}>
                    Remove
                  </Button>
                </div>
                <div className="space-y-3">
                  <Field label="Subject" hint="Leave empty to reply in the same conversation (Re: the first subject).">
                    <Input value={f.subject} maxLength={300} onChange={(e) => set({ subject: e.target.value })} />
                  </Field>
                  <Field label="Message">
                    <Textarea rows={6} value={f.body} onChange={(e) => set({ body: e.target.value })} />
                  </Field>
                </div>
              </div>
            );
          })}
          <p className="text-xs text-stone-500">
            Sent in the same Gmail thread, at the same careful pace and under the same limits as everything else, and only after Worklane has looked at the conversation and found no answer.{" "}
            {variables}
          </p>
        </div>
      )}
    </Card>
  );
}
