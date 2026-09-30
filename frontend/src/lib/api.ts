"use client";

import { useCallback, useEffect, useState } from "react";

const BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const TOKEN_KEY = "easybid_token";

export const getToken = () => (typeof window === "undefined" ? null : localStorage.getItem(TOKEN_KEY));
export const setToken = (token: string) => localStorage.setItem(TOKEN_KEY, token);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

function errorMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`).join("; ");
  }
  return `Request failed (${status})`;
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const token = getToken();
  let res: Response;
  try {
    res = await fetch(`${BASE}/api${path}`, {
      method: init.method ?? "GET",
      headers: {
        ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    });
  } catch {
    throw new Error(`Cannot reach the API at ${BASE}`);
  }
  if (res.status === 401 && path !== "/auth/login") {
    clearToken();
    // A full reload, so no page keeps state from the expired session.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = "/login";
    throw new Error("Session expired");
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorMessage(body, res.status));
  return body as T;
}

/**
 * Load a GET endpoint; `reload()` fetches it again. Pass null to skip.
 *
 * `loading` is true until there is a result to show. `fetching` is true whenever a request is in flight,
 * which includes a reload and, with `keepPrevious`, a move to another path while the last result stays on screen.
 */
export function useApi<T>(path: string | null, options: { keepPrevious?: boolean } = {}) {
  const keepPrevious = options.keepPrevious ?? false;
  const [state, setState] = useState<{ path?: string; data?: T; error?: string }>({});
  const [version, setVersion] = useState(0);
  const [settled, setSettled] = useState("");
  const request = `${version}:${path}`;

  useEffect(() => {
    if (!path) return;
    let alive = true;
    api<T>(path)
      .then((data) => alive && setState({ path, data }))
      .catch(
        (e: Error) =>
          alive && setState((s) => ({ data: keepPrevious || s.path === path ? s.data : undefined, path, error: e.message })),
      )
      .finally(() => alive && setSettled(request));
    return () => {
      alive = false;
    };
  }, [path, request, keepPrevious]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  // `data` can legitimately be null (an endpoint with nothing to return), so this is tracked by path.
  const showing = state.path === path || (keepPrevious && state.path !== undefined);
  return {
    data: showing ? state.data : undefined,
    error: state.path === path ? state.error : undefined,
    loading: path !== null && !showing,
    fetching: path !== null && settled !== request,
    reload,
  };
}

export type Mode = "manual" | "semi" | "auto";
export type PromptKind = "selection" | "proposal";

export interface Settings {
  paused: boolean;
  mode: Mode;
  poll_interval_seconds: number;
  max_projects_per_cycle: number;
  daily_bid_cap: number;
  semi_auto_min_score: number;
  skill_ids: number[];
  skill_names: string[];
  min_skill_matches: number;
  blocked_skill_ids: number[];
  blocked_skill_names: string[];
  project_types: ("fixed" | "hourly")[];
  currencies: string[];
  languages: string[];
  min_fixed_budget: number;
  min_hourly_rate: number;
  max_bid_count: number;
  max_age_minutes: number;
  min_score: number;
  exclude_keywords: string[];
  skip_upgrades: string[];
  fixed_budget_position: number;
  hourly_rate: number;
  default_period_days: number;
  hourly_weekly_hours: number;
  milestone_percentage: number;
  selection_model: string;
  proposal_model: string;
  proposal_min_chars: number;
  proposal_max_chars: number;
}

export interface Proposal {
  id: number;
  project_id: number;
  prompt_id: number | null;
  text: string;
  amount: number;
  period: number;
  model: string;
  status: string;
  auto: boolean;
  error: string | null;
  freelancer_bid_id: number | null;
  bid_status: string | null;
  created_at: string;
  sent_at: string | null;
}

export interface Project {
  id: number;
  title: string;
  description: string;
  url: string;
  type: "fixed" | "hourly";
  currency: string;
  budget_min: number | null;
  budget_max: number | null;
  weekly_hours: number | null;
  bid_count: number;
  bid_avg: number | null;
  skills: string[];
  skill_ids: number[];
  language: string | null;
  upgrades: string[];
  submitted_at: string | null;
  status: string;
  score: number | null;
  reason: string | null;
  created_at: string;
  proposal?: Proposal | null;
}

export interface ProposalWithProject extends Proposal {
  project: Project;
}

export interface Prompt {
  id: number;
  kind: PromptKind;
  version: number;
  content: string;
  note: string;
  is_active: boolean;
  created_at: string;
}

export interface PromptTest {
  apply: boolean | null;
  reason: string | null;
  text: string | null;
  chars: number | null;
  amount: number | null;
  period: number | null;
}

export interface ProfileItem {
  id: number;
  kind: "bio" | "skill" | "project" | "link";
  title: string;
  content: string;
  is_active: boolean;
}

export interface Skill {
  id: number;
  name: string;
}

export interface Account {
  id: number;
  username: string;
  display_name: string | null;
  skills: Skill[];
}

export interface Stats {
  paused: boolean;
  mode: Mode;
  skills_selected: number;
  ai_problem: string | null;
  proposal_prompt_active: boolean;
  last_cycle: string | null;
  account: {
    username?: string;
    membership?: string | null;
    bids_remaining?: number | null;
    balance_usd?: number | null;
    preferred_freelancer?: boolean;
    freelancer_verified?: boolean;
    identity_verified?: boolean;
    payment_verified?: boolean;
  };
  account_problem: string | null;
  waiting: string | null;
  currency_min_balance_usd: Record<string, number>;
  projects_24h: Record<string, number>;
  proposals: Record<string, number>;
  sent_today: number;
  daily_bid_cap: number;
  awarded: number;
  prompts: { version: number; is_active: boolean; sent: number; awarded: number }[];
}

export interface LogEntry {
  id: number;
  level: string;
  event: string;
  message: string;
  project_id: number | null;
  created_at: string;
}

export function budgetLabel(p: Project): string {
  const range = p.budget_min && p.budget_max ? `${p.budget_min}–${p.budget_max}` : `${p.budget_max ?? p.budget_min ?? "?"}`;
  return `${range} ${p.currency}${p.type === "hourly" ? "/hr" : ""}`;
}

export function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 1440) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} d ago`;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

/** Build "/path?a=1&b=2", leaving out empty values. */
export function withQuery(path: string, params: Record<string, string | number | null | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") query.set(key, String(value));
  }
  const text = query.toString();
  return text ? `${path}?${text}` : path;
}

/**
 * One page of a list endpoint, with its search text and filters.
 * Changing the search or a filter goes back to page 1.
 */
export function usePaged<T>(path: string, options: { pageSize?: number; filters?: Record<string, string> } = {}) {
  const { pageSize = 20, filters = {} } = options;
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const scope = JSON.stringify(filters);
  const [seenScope, setSeenScope] = useState(scope);
  if (seenScope !== scope) {
    setSeenScope(scope);
    setPage(1);
  }

  const search = useCallback((text: string) => {
    setQ(text);
    setPage(1);
  }, []);

  // The previous page stays on screen while the next one loads, so the list never blanks out.
  const result = useApi<Page<T>>(withQuery(path, { ...filters, q, page, page_size: pageSize }), { keepPrevious: true });
  // A page can empty out after an action (approve, delete); step back instead of showing nothing.
  const lastPage = result.data?.pages;
  if (lastPage !== undefined && page > lastPage) setPage(lastPage);

  return { ...result, page, setPage, q, search };
}
