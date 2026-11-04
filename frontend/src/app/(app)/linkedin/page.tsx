"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Badge, Button, Card, Empty, Field, Input, Loading, Notice, PageHeader, Select, Textarea } from "@/components/ui";
import {
  api,
  apiBlob,
  timeAgo,
  useApi,
  useBlobUrl,
  type LinkedInAccount,
  type LinkedInIdea,
  type LinkedInOverview,
  type LinkedInResearch,
  type LinkedInPost,
  type LinkedInTarget,
  type PosterSpec,
} from "@/lib/api";

const TABS = [
  { key: "review", label: "To review", statuses: "draft,failed" },
  { key: "scheduled", label: "Scheduled", statuses: "approved,posting" },
  { key: "posted", label: "Posted", statuses: "posted" },
  { key: "all", label: "All", statuses: "" },
];

const NAMES: Record<LinkedInTarget, string> = { personal: "Personal profile", company: "Company page" };

function localInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function Connections({ overview, reload }: { overview: LinkedInOverview; reload: () => void }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function connect(target: LinkedInTarget) {
    setBusy(target);
    setError("");
    try {
      const r = await api<{ url: string }>(`/linkedin/connect/${target}`, { method: "POST" });
      window.location.assign(r.url);
    } catch (e) {
      setError((e as Error).message);
      setBusy("");
    }
  }

  async function disconnect(target: LinkedInTarget) {
    if (!confirm(`Disconnect the ${NAMES[target].toLowerCase()} from LinkedIn?`)) return;
    setBusy(target);
    try {
      await api(`/linkedin/accounts/${target}`, { method: "DELETE" });
      reload();
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy("");
  }

  return (
    <Card title="Connections">
      <Notice>{error}</Notice>
      <div className="grid gap-4 md:grid-cols-2">
        {overview.accounts.map((a: LinkedInAccount) => {
          const warn = a.connected && a.days_left !== null && a.days_left < 8;
          return (
            <div key={a.target} className="rounded-[12px] border border-stone-200 p-4">
              <div className="flex items-center justify-between gap-2">
                <div className="font-medium text-stone-900">{NAMES[a.target]}</div>
                <Badge tone={a.connected ? (warn ? "amber" : "green") : "gray"}>{a.connected ? "connected" : "not connected"}</Badge>
              </div>
              <p className="mt-1 text-sm text-stone-500">
                {a.connected
                  ? `${a.name}${a.days_left !== null ? ` · login lasts ${a.days_left} more days` : ""}`
                  : a.target === "company"
                    ? "Posts as the company page. Needs LinkedIn's Community Management API approval."
                    : "Posts as you."}
              </p>
              {a.problem && <p className="mt-2 text-sm text-amber-800">{a.problem}</p>}
              <div className="mt-3 flex gap-2">
                <Button variant="primary" loading={busy === a.target} disabled={!a.configured} onClick={() => connect(a.target)}>
                  {a.connected ? "Connect again" : "Connect"}
                </Button>
                {a.connected && (
                  <Button onClick={() => disconnect(a.target)} disabled={busy === a.target}>
                    Disconnect
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <p className="mt-3 text-xs text-stone-500">
        Add this as a redirect URL in each LinkedIn developer app: <code className="rounded bg-stone-100 px-1">{overview.redirect_uri}</code>. LinkedIn logins last 60
        days and are renewed with the Connect button; you get a Telegram message a week before.
      </p>
    </Card>
  );
}

function PosterEditor({ spec, onChange }: { spec: PosterSpec; onChange: (s: PosterSpec) => void }) {
  const set = (patch: Partial<PosterSpec>) => onChange({ ...spec, ...patch });
  const hasPoints = spec.template === "points" || spec.template === "checklist" || spec.template === "compare";
  return (
    <div className="space-y-3 rounded-[12px] border border-stone-200 bg-stone-50 p-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Layout">
          <Select value={spec.template} onChange={(e) => set({ template: e.target.value as PosterSpec["template"] })}>
            <option value="points">Headline and numbered points</option>
            <option value="checklist">Headline and ticked checklist</option>
            <option value="compare">Common way vs better way</option>
            <option value="stat">One big number</option>
            <option value="statement">One statement</option>
          </Select>
        </Field>
        <Field label="Label (top right)">
          <Input value={spec.kicker} maxLength={26} onChange={(e) => set({ kicker: e.target.value })} />
        </Field>
        <Field label="Footer note">
          <Input value={spec.footer} maxLength={40} onChange={(e) => set({ footer: e.target.value })} />
        </Field>
      </div>
      {spec.template === "stat" ? (
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Number">
            <Input value={spec.stat} maxLength={14} onChange={(e) => set({ stat: e.target.value })} />
          </Field>
          <div className="sm:col-span-2">
            <Field label="What it means">
              <Input value={spec.stat_label} maxLength={110} onChange={(e) => set({ stat_label: e.target.value })} />
            </Field>
          </div>
        </div>
      ) : (
        <Field label={spec.template === "statement" ? "Statement" : "Headline"}>
          <Input value={spec.headline} maxLength={110} onChange={(e) => set({ headline: e.target.value })} />
        </Field>
      )}
      {hasPoints &&
        spec.points.map((p, i) => (
          <div key={i} className="grid gap-2 sm:grid-cols-[1fr_2fr_auto]">
            <Input
              value={p.title}
              maxLength={70}
              placeholder={spec.template === "compare" ? "Common or wrong way" : `Point ${i + 1}`}
              onChange={(e) => set({ points: spec.points.map((q, j) => (j === i ? { ...q, title: e.target.value } : q)) })}
            />
            <Input
              value={p.text}
              maxLength={140}
              placeholder={spec.template === "compare" ? "The better way" : "One line of detail"}
              onChange={(e) => set({ points: spec.points.map((q, j) => (j === i ? { ...q, text: e.target.value } : q)) })}
            />
            <Button onClick={() => set({ points: spec.points.filter((_, j) => j !== i) })}>Remove</Button>
          </div>
        ))}
      {hasPoints && spec.points.length < (spec.template === "compare" ? 4 : 5) && <Button onClick={() => set({ points: [...spec.points, { title: "", text: "" }] })}>Add row</Button>}
      {!hasPoints && (
        <Field label="Small print under it">
          <Input value={spec.caption} maxLength={200} onChange={(e) => set({ caption: e.target.value })} />
        </Field>
      )}
    </div>
  );
}

const BLANK_SPEC: PosterSpec = { template: "points", kicker: "", headline: "", points: [{ title: "", text: "" }, { title: "", text: "" }], stat: "", stat_label: "", caption: "", footer: "" };

function PostCard({ initial, onChanged }: { initial: LinkedInPost; onChanged: () => void }) {
  const [post, setPost] = useState(initial);
  const [text, setText] = useState(initial.text);
  const [comment, setComment] = useState(initial.first_comment);
  const [when, setWhen] = useState(localInput(initial.scheduled_for));
  const [spec, setSpec] = useState<PosterSpec | null>(initial.poster_spec);
  const [editingPoster, setEditingPoster] = useState(false);
  const [brief, setBrief] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [version, setVersion] = useState(0);
  const editable = ["draft", "approved", "failed"].includes(post.status);
  const poster = useBlobUrl(post.has_poster ? `/linkedin/posts/${post.id}/poster.png` : null, version);
  const dirty = text !== post.text || comment !== post.first_comment || JSON.stringify(spec) !== JSON.stringify(post.poster_spec);

  async function run<T>(name: string, fn: () => Promise<T>, done?: (r: T) => void) {
    setBusy(name);
    setError("");
    setNote("");
    try {
      const r = await fn();
      done?.(r);
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy("");
  }

  const adopt = (p: LinkedInPost) => {
    setPost(p);
    setText(p.text);
    setComment(p.first_comment);
    setSpec(p.poster_spec);
    setWhen(localInput(p.scheduled_for));
    setVersion((v) => v + 1);
    onChanged();
  };

  const patch = (body: object) => api<LinkedInPost>(`/linkedin/posts/${post.id}`, { method: "PATCH", body });
  const save = () => run("save", () => patch({ text, first_comment: comment, ...(spec ? { poster_spec: spec } : {}) }), adopt);
  const act = (name: string, path: string, body?: object) => run(name, async () => {
    if (dirty && editable) await patch({ text, first_comment: comment, ...(spec ? { poster_spec: spec } : {}) });
    return api<LinkedInPost>(`/linkedin/posts/${post.id}/${path}`, { method: "POST", body: body ?? {} });
  }, adopt);

  async function download() {
    const blob = await apiBlob(`/linkedin/posts/${post.id}/poster.png`);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `poster-${post.id}.png`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Badge tone={post.target === "company" ? "brand" : "blue"}>{NAMES[post.target]}</Badge>
        <Badge>{post.status}</Badge>
        <span className="text-sm font-medium text-stone-800">{post.topic || "Untitled"}</span>
        <span className="text-xs text-stone-500">
          {post.pillar} · {post.post_date}
          {post.posted_at ? ` · posted ${timeAgo(post.posted_at)}` : ""}
        </span>
        {post.linkedin_url && (
          <a className="ml-auto text-sm text-brand-700 underline" href={post.linkedin_url} target="_blank" rel="noreferrer">
            View on LinkedIn
          </a>
        )}
      </div>
      <Notice>{error}</Notice>
      <Notice>{post.error}</Notice>
      <Notice tone="green">{note}</Notice>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-3">
          <Textarea rows={14} value={text} disabled={!editable} onChange={(e) => setText(e.target.value)} />
          <div className="text-xs text-stone-500">
            {text.length} / 3000 characters
          </div>
          {(post.signals?.why_now || !!post.signals?.sources?.length) && (
            <details className="rounded-[10px] bg-stone-50 px-3 py-2 text-xs text-stone-600">
              <summary className="cursor-pointer font-medium text-stone-700">Why this topic, and where it comes from</summary>
              {post.signals.angle && (
                <p className="mt-2">
                  <span className="font-medium">Angle:</span> {post.signals.angle}
                </p>
              )}
              {post.signals.why_now && (
                <p className="mt-1">
                  <span className="font-medium">Why now:</span> {post.signals.why_now}
                </p>
              )}
              {!!post.signals.sources?.length && (
                <ul className="mt-2 list-disc space-y-0.5 pl-4">
                  {post.signals.sources.slice(0, 6).map((src) => (
                    <li key={src.url}>
                      <a className="text-brand-700 underline" href={src.url} target="_blank" rel="noreferrer">
                        {src.title || src.url}
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </details>
          )}
          {editable && (
            <Field label="First comment (posted right after the post, good for a link)">
              <Input value={comment} maxLength={1000} onChange={(e) => setComment(e.target.value)} />
            </Field>
          )}
        </div>
        <div className="space-y-3">
          {poster ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={poster} alt={post.alt_text || "Poster"} className="w-full rounded-[12px] border border-stone-200" />
          ) : (
            <div className="grid aspect-[4/5] place-items-center rounded-[12px] border border-dashed border-stone-300 text-sm text-stone-500">
              {post.has_poster ? "Loading poster…" : "Text only"}
            </div>
          )}
          {editable && (
            <div className="flex flex-wrap gap-2">
              {!spec && <Button onClick={() => { setSpec(BLANK_SPEC); setEditingPoster(true); }}>Add a poster</Button>}
              {spec && <Button onClick={() => setEditingPoster(!editingPoster)}>{editingPoster ? "Hide poster editor" : "Edit poster"}</Button>}
              {spec && <Button loading={busy === "remove"} onClick={() => run("remove", () => patch({ remove_poster: true }), adopt)}>Remove poster</Button>}
            </div>
          )}
          {post.has_poster && (
            <Button onClick={() => run("download", download)} loading={busy === "download"}>
              Download poster
            </Button>
          )}
        </div>
      </div>
      {editingPoster && spec && editable && (
        <div className="mt-4">
          <PosterEditor spec={spec} onChange={setSpec} />
          <p className="mt-2 text-xs text-stone-500">Press Save changes to redraw the poster with these words.</p>
        </div>
      )}
      {editable && (
        <div className="mt-4 flex flex-wrap items-end gap-2 border-t border-stone-200 pt-4">
          <Button loading={busy === "save"} disabled={!dirty} onClick={save}>
            Save changes
          </Button>
          {post.status !== "approved" && (
            <>
              <div className="w-56">
                <Field label="Post at (your browser's time)">
                  <Input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
                </Field>
              </div>
              <Button variant="primary" loading={busy === "approve"} onClick={() => act("approve", "approve", when ? { scheduled_for: new Date(when).toISOString() } : {})}>
                Approve
              </Button>
            </>
          )}
          {post.status === "approved" && (
            <Button loading={busy === "unapprove"} onClick={() => act("unapprove", "unapprove")}>
              Back to draft
            </Button>
          )}
          <Button loading={busy === "now"} onClick={() => confirm("Post this to LinkedIn right now?") && act("now", "post-now")}>
            Post now
          </Button>
          <Button onClick={() => navigator.clipboard.writeText(text).then(() => setNote("Text copied."))}>Copy text</Button>
          <Button loading={busy === "manual"} onClick={() => confirm("Mark as posted? Use this when you posted it by hand.") && act("manual", "mark-posted")}>
            I posted it myself
          </Button>
          <Button loading={busy === "reject"} onClick={() => act("reject", "reject")}>
            Reject
          </Button>
          <div className="ml-auto flex items-end gap-2">
            <div className="w-64">
              <Field label="Rewrite on a topic (optional)">
                <Input value={brief} maxLength={1000} placeholder="Leave blank to let it pick" onChange={(e) => setBrief(e.target.value)} />
              </Field>
            </div>
            <Button loading={busy === "rewrite"} onClick={() => act("rewrite", "rewrite", { target: post.target, brief })}>
              Rewrite
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}

function Research() {
  const research = useApi<LinkedInResearch>("/linkedin/research");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const data = research.data;

  async function refresh() {
    setBusy(true);
    setError("");
    try {
      await api("/linkedin/research/refresh", { method: "POST" });
      research.reload();
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  }

  return (
    <details className="rounded-[12px] border border-stone-200 bg-white px-4 py-3">
      <summary className="cursor-pointer text-sm font-medium text-stone-800">
        Today&apos;s research
        <span className="ml-2 font-normal text-stone-500">
          {data?.found ? `${data.sources?.length ?? 0} sources · ${data.via === "search+feeds" ? "web search and news feeds" : "news feeds"}` : "not looked up yet today"}
        </span>
      </summary>
      <Notice>{error}</Notice>
      <p className="mt-2 text-xs text-stone-500">
        Every day the web is searched for what happened in your fields, and the posts are written from that. Both profiles share it. Nothing comes from Freelancer.
      </p>
      {data?.digest && <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-[10px] bg-stone-50 p-3 text-xs text-stone-700">{data.digest}</pre>}
      <div className="mt-3">
        <Button loading={busy} onClick={refresh}>
          {busy ? "Searching…" : "Search again"}
        </Button>
      </div>
    </details>
  );
}

function Studio({ target, today, onDone }: { target: LinkedInTarget; today: number; onDone: () => void }) {
  const [brief, setBrief] = useState("");
  const [ideas, setIdeas] = useState<LinkedInIdea[] | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function write(topic: string, key: string) {
    setBusy(key);
    setError("");
    try {
      await api("/linkedin/posts/generate", { method: "POST", body: { target, brief: topic } });
      setBrief("");
      setIdeas(null);
      onDone();
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy("");
  }

  async function suggest() {
    setBusy("ideas");
    setError("");
    try {
      setIdeas(await api<LinkedInIdea[]>("/linkedin/ideas", { method: "POST", body: { target, count: 5 } }));
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy("");
  }

  return (
    <Card title={`${NAMES[target]}: write a post`}>
      <Notice>{error}</Notice>
      <p className="mb-3 text-sm text-stone-500">
        {today > 0 ? `${today} post${today > 1 ? "s" : ""} written for today.` : "Today's post is not written yet; it is written automatically at the time set in Settings, or you can write it now."}{" "}
        Each button adds a new post: it researches today, picks a topic you have not covered, and writes it.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-64 flex-1">
          <Field label="Your own topic (optional)" hint="Leave blank and it chooses from this week's research and what this profile can speak about.">
            <Input value={brief} maxLength={1000} placeholder="e.g. What the new Next.js caching defaults mean for existing apps" onChange={(e) => setBrief(e.target.value)} />
          </Field>
        </div>
        <Button variant="primary" loading={busy === "write"} disabled={!!busy && busy !== "write"} onClick={() => write(brief, "write")}>
          {busy === "write" ? "Researching and writing…" : brief.trim() ? "Write about this" : "Write a new post"}
        </Button>
        <Button loading={busy === "ideas"} disabled={!!busy && busy !== "ideas"} onClick={suggest}>
          {busy === "ideas" ? "Thinking…" : "Suggest topics"}
        </Button>
      </div>
      {ideas && (
        <div className="mt-4 grid gap-2 md:grid-cols-2">
          {ideas.map((i) => {
            const key = `idea:${i.topic}`;
            return (
              <button
                key={key}
                type="button"
                disabled={!!busy}
                onClick={() => write(i.topic + (i.angle ? `. Angle: ${i.angle}` : ""), key)}
                className="rounded-[12px] border border-stone-200 bg-white p-3 text-left transition hover:border-brand-300 hover:bg-brand-50/40 disabled:opacity-50"
              >
                <div className="text-sm font-medium text-stone-900">{i.topic}</div>
                {i.angle && <div className="mt-1 text-xs text-stone-600">{i.angle}</div>}
                <div className="mt-1.5 text-[11px] text-stone-500">
                  {i.pillar} · {i.why_now}
                </div>
                {busy === key && <div className="mt-1 text-xs text-brand-700">Writing…</div>}
              </button>
            );
          })}
        </div>
      )}
    </Card>
  );
}

function TargetPanel({ target, overview, reloadOverview }: { target: LinkedInTarget; overview: LinkedInOverview; reloadOverview: () => void }) {
  const [tab, setTab] = useState("review");
  const statuses = TABS.find((t) => t.key === tab)?.statuses ?? "";
  const posts = useApi<LinkedInPost[]>(`/linkedin/posts?limit=60&target=${target}${statuses ? `&status=${statuses}` : ""}`, { keepPrevious: true });
  const counts = overview.counts[target] ?? {};
  const reloadAll = () => {
    reloadOverview();
    posts.reload();
  };
  const account = overview.accounts.find((a) => a.target === target);

  return (
    <div className="space-y-5">
      {account && !account.connected && (
        <Notice tone="amber">
          Not connected to LinkedIn, so nothing can be published from here yet. Drafts are still written: use Copy text and Download poster, post by hand, then press &quot;I posted it myself&quot;.
        </Notice>
      )}
      <Studio target={target} today={overview.today[target] ?? 0} onDone={reloadAll} />
      <Research />
      <div className="flex flex-wrap gap-2">
        {TABS.map((t) => {
          const n = t.statuses ? t.statuses.split(",").reduce((sum, s) => sum + (counts[s] ?? 0), 0) : undefined;
          return (
            <Button key={t.key} variant={tab === t.key ? "primary" : "secondary"} onClick={() => setTab(t.key)}>
              {t.label}
              {n ? ` (${n})` : ""}
            </Button>
          );
        })}
      </div>
      <Notice>{posts.error}</Notice>
      {posts.loading ? (
        <Loading />
      ) : posts.data && posts.data.length > 0 ? (
        <div className="space-y-5">
          {posts.data.map((p) => (
            <PostCard key={`${p.id}-${p.status}`} initial={p} onChanged={reloadOverview} />
          ))}
        </div>
      ) : (
        <Empty>Nothing here yet. Turn on the daily post in Settings, or write one above.</Empty>
      )}
    </div>
  );
}

function Content() {
  const params = useSearchParams();
  const [target, setTarget] = useState<LinkedInTarget>("personal");
  const overview = useApi<LinkedInOverview>("/linkedin/overview");
  const connect = params.get("connect");

  if (overview.loading || !overview.data) return <Loading />;
  const data = overview.data;
  const toReview = (t: LinkedInTarget) => (data.counts[t]?.draft ?? 0) + (data.counts[t]?.failed ?? 0);

  return (
    <>
      <PageHeader title="LinkedIn" subtitle="A researched post a day for your profile and another for the company page. Review, tweak, approve, or write a new one any time." />
      {connect === "connected" && <Notice tone="green">LinkedIn connected.</Notice>}
      {connect === "error" && <Notice>{params.get("message") || "LinkedIn could not be connected."}</Notice>}
      <Notice>{overview.error}</Notice>
      <div className="space-y-6">
        <Connections overview={data} reload={overview.reload} />
        <div role="tablist" className="flex gap-2 border-b border-stone-200">
          {(["personal", "company"] as LinkedInTarget[]).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={target === t}
              onClick={() => setTarget(t)}
              className={`-mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition ${target === t ? "border-brand-600 text-brand-700" : "border-transparent text-stone-500 hover:text-stone-800"}`}
            >
              {NAMES[t]}
              {toReview(t) > 0 && <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] text-amber-800">{toReview(t)} to review</span>}
            </button>
          ))}
        </div>
        <TargetPanel key={target} target={target} overview={data} reloadOverview={overview.reload} />
      </div>
    </>
  );
}

export default function LinkedInPage() {
  return (
    <Suspense fallback={<Loading />}>
      <Content />
    </Suspense>
  );
}
