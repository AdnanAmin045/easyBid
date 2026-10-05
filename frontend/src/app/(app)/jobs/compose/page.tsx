"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, Button, Card, Field, Input, Notice, PageHeader, Select, Textarea } from "@/components/ui";
import { api, useApi, type Application, type Extraction, type Resume } from "@/lib/api";

const MANUAL = "__manual__";

function Fact({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div>
      <dt className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-stone-500">{label}</dt>
      <dd className="mt-0.5 text-sm text-stone-900">{value}</dd>
    </div>
  );
}

export default function ComposePage() {
  const router = useRouter();
  const { data: resumes } = useApi<Resume[]>("/jobs/resumes");
  const [text, setText] = useState("");
  const [result, setResult] = useState<Extraction | null>(null);
  const [company, setCompany] = useState("");
  const [role, setRole] = useState("");
  const [choice, setChoice] = useState("");
  const [manual, setManual] = useState("");
  const [cc, setCc] = useState("");
  const [resumeId, setResumeId] = useState<string | null>(null);
  const [busy, setBusy] = useState<"" | "extract" | "write">("");
  const [error, setError] = useState("");

  const defaultResume = resumes?.find((r) => r.is_default);
  const selectedResume = resumeId ?? (defaultResume ? String(defaultResume.id) : "");
  const recipient = choice === MANUAL || !choice ? manual.trim() : choice;
  const ccList = cc.split(",").map((s) => s.trim()).filter(Boolean);
  const chosen = result?.emails.find((e) => e.email === choice);

  async function analyze() {
    setBusy("extract");
    setError("");
    try {
      const data = await api<Extraction>("/jobs/extract", { method: "POST", body: { text } });
      setResult(data);
      setCompany(data.company);
      setRole(data.role);
      const firstValid = data.emails.find((e) => e.valid) ?? data.emails[0];
      setChoice(firstValid ? firstValid.email : MANUAL);
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy("");
  }

  async function write() {
    if (!result) return;
    setBusy("write");
    setError("");
    try {
      const created = await api<Application>("/jobs/applications", {
        method: "POST",
        body: {
          source_text: text,
          details: { ...result, company, role },
          to_email: recipient,
          cc: ccList,
          resume_id: selectedResume ? Number(selectedResume) : null,
        },
      });
      router.push(`/jobs/applications/${created.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy("");
    }
  }

  return (
    <>
      <PageHeader
        title="New application"
        subtitle="Paste the job description. The recipient and the job details are read from it, then the AI writes the email for your review."
      />
      <Notice>{error}</Notice>

      <div className="grid gap-6 lg:grid-cols-[1.15fr_1fr]">
        <Card title="1 · Job description">
          <Textarea
            rows={18}
            value={text}
            maxLength={30000}
            placeholder="Paste the full posting: title, company, requirements, and how to apply."
            onChange={(e) => {
              setText(e.target.value);
              setResult(null);
            }}
          />
          <div className="mt-3 flex items-center justify-between gap-3">
            <span className="tabular font-mono text-[11px] text-stone-400">{text.length.toLocaleString()} / 30,000</span>
            <Button variant="dark" loading={busy === "extract"} disabled={busy !== "" || text.trim().length < 20} onClick={analyze}>
              {busy === "extract" ? "Reading…" : result ? "Read again" : "Read description"}
            </Button>
          </div>
        </Card>

        <Card title="2 · Recipient and details">
          {!result ? (
            <p className="py-10 text-center text-sm text-stone-500">The details appear here once the description is read.</p>
          ) : (
            <div className="space-y-5">
              {result.warning && <Notice tone="amber">{result.warning}</Notice>}
              {result.apply_via === "link" && (
                <Notice tone="amber">
                  This posting asks you to apply through a link{result.apply_link ? `: ${result.apply_link}` : ""}. An email may not be read.
                </Notice>
              )}

              <fieldset>
                <legend className="mb-2 text-[13px] font-medium text-stone-700">Send to</legend>
                <div className="space-y-1.5">
                  {result.emails.map((e) => (
                    <label
                      key={e.email}
                      className={`flex cursor-pointer items-start gap-3 rounded-[6px] border px-3 py-2 text-sm transition ${
                        choice === e.email ? "border-brand-400 bg-brand-50/60" : "border-stone-200 hover:border-stone-300"
                      }`}
                    >
                      <input type="radio" name="recipient" className="mt-1 accent-brand-600" checked={choice === e.email} onChange={() => setChoice(e.email)} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium text-stone-900">{e.email}</span>
                        {(!e.valid || e.reason) && <span className={`block text-xs ${e.valid ? "text-stone-500" : "text-red-700"}`}>{e.reason}</span>}
                        {e.applied_before && (
                          <span className="block text-xs text-amber-800">You applied here on {new Date(e.applied_before).toLocaleDateString()}</span>
                        )}
                      </span>
                      <Badge tone={e.valid ? "green" : "red"}>{e.valid ? "verified" : "invalid"}</Badge>
                    </label>
                  ))}
                  <label
                    className={`flex cursor-pointer items-center gap-3 rounded-[6px] border px-3 py-2 text-sm ${
                      choice === MANUAL ? "border-brand-400 bg-brand-50/60" : "border-stone-200 hover:border-stone-300"
                    }`}
                  >
                    <input type="radio" name="recipient" className="accent-brand-600" checked={choice === MANUAL} onChange={() => setChoice(MANUAL)} />
                    <span className="shrink-0 text-stone-700">{result.emails.length ? "Other address" : "No address found. Enter one"}</span>
                    <Input
                      type="email"
                      value={manual}
                      placeholder="hr@company.com"
                      onFocus={() => setChoice(MANUAL)}
                      onChange={(e) => setManual(e.target.value)}
                      aria-label="Recipient email"
                    />
                  </label>
                </div>
              </fieldset>

              <Field label="CC" hint="Optional, comma-separated.">
                <Input value={cc} placeholder="sara@company.com" onChange={(e) => setCc(e.target.value)} />
              </Field>

              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Company">
                  <Input value={company} maxLength={200} onChange={(e) => setCompany(e.target.value)} />
                </Field>
                <Field label="Role">
                  <Input value={role} maxLength={200} onChange={(e) => setRole(e.target.value)} />
                </Field>
              </div>

              <dl className="grid gap-3 rounded-[6px] bg-stone-50 p-3 sm:grid-cols-2">
                <Fact label="Location" value={[result.location, result.work_mode].filter(Boolean).join(" · ")} />
                <Fact label="Addressed to" value={result.recipient_name} />
                <Fact label="Deadline" value={result.deadline} />
                <Fact label="Skills asked for" value={result.required_skills.join(", ")} />
              </dl>

              {result.apply_instructions.length > 0 && (
                <div>
                  <div className="mb-1.5 font-mono text-[10.5px] uppercase tracking-[0.12em] text-stone-500">Instructions the email will follow</div>
                  <ul className="space-y-1 text-sm text-stone-800">
                    {result.apply_instructions.map((line) => (
                      <li key={line} className="flex gap-2">
                        <span className="text-brand-600" aria-hidden="true">
                          ›
                        </span>
                        {line}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <Field label="Attach CV">
                <Select value={selectedResume} onChange={(e) => setResumeId(e.target.value)}>
                  <option value="">No attachment</option>
                  {resumes?.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                      {r.is_default ? " (default)" : ""}
                    </option>
                  ))}
                </Select>
              </Field>

              <div className="flex items-center justify-between gap-3 border-t border-stone-200 pt-4">
                <span className="text-xs text-stone-500">
                  {chosen && !chosen.valid ? "This address failed verification." : "Nothing is sent until you approve it."}
                </span>
                <Button variant="primary" loading={busy === "write"} disabled={busy !== "" || !recipient} onClick={write}>
                  {busy === "write" ? "Writing email…" : "Write the email"}
                </Button>
              </div>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
