"use client";

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

const control =
  "w-full rounded-[6px] border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 shadow-[inset_0_1px_0_rgb(0_0_0/0.02)] outline-none transition placeholder:text-stone-400 focus:border-brand-500 focus:ring-3 focus:ring-brand-100 disabled:bg-stone-100 disabled:text-stone-500";

const variants = {
  primary: "bg-brand-600 text-white shadow-[0_1px_0_rgb(0_0_0/0.15)] hover:bg-brand-700",
  secondary: "border border-stone-300 bg-white text-stone-800 hover:border-stone-400 hover:bg-stone-50",
  dark: "bg-graphite-900 text-white hover:bg-graphite-800",
  danger: "border border-red-200 bg-white text-red-700 hover:bg-red-50",
};

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={`shrink-0 animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" className="opacity-25" />
      <path fill="currentColor" className="opacity-75" d="M4 12a8 8 0 0 1 8-8V0C5.4 0 0 5.4 0 12h4z" />
    </svg>
  );
}

/** Shown in place of content that has not loaded yet. */
export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 py-16 text-sm text-stone-500">
      <Spinner className="h-5 w-5" />
      {label}
    </div>
  );
}

/** `loading` shows a spinner and blocks the button, so the action cannot be fired twice. */
export function Button({
  variant = "secondary",
  className = "",
  loading = false,
  disabled,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof variants; loading?: boolean }) {
  return (
    <button
      type="button"
      {...props}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`inline-flex items-center justify-center gap-2 rounded-[6px] px-3 py-2 text-sm font-medium transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500 disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`}
    >
      {loading && <Spinner />}
      {children}
    </button>
  );
}

export const Input = (props: InputHTMLAttributes<HTMLInputElement>) => (
  <input {...props} className={`${control} ${props.className ?? ""}`} />
);

export const Textarea = (props: TextareaHTMLAttributes<HTMLTextAreaElement>) => (
  <textarea {...props} className={`${control} leading-relaxed ${props.className ?? ""}`} />
);

export const Select = (props: SelectHTMLAttributes<HTMLSelectElement>) => (
  <select {...props} className={`${control} ${props.className ?? ""}`} />
);

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-medium text-stone-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-stone-500">{hint}</span>}
    </label>
  );
}

export function Card({ title, action, children, className = "" }: { title?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-[8px] border border-stone-300/70 bg-white p-5 shadow-[0_1px_2px_rgb(28_25_23/0.04)] ${className}`}>
      {(title || action) && (
        <div className="mb-4 flex items-center justify-between gap-3 border-b border-stone-200 pb-3">
          <h2 className="font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-stone-600">{title}</h2>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

const tones: Record<string, string> = {
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  red: "bg-red-50 text-red-700 ring-red-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  blue: "bg-sky-50 text-sky-800 ring-sky-200",
  brand: "bg-brand-50 text-brand-700 ring-brand-200",
  gray: "bg-stone-100 text-stone-600 ring-stone-200",
};

const statusTone: Record<string, string> = {
  sent: "green",
  awarded: "green",
  active: "blue",
  proposed: "blue",
  pending: "amber",
  sending: "amber",
  draft: "amber",
  new: "gray",
  processing: "gray",
  filtered: "gray",
  skipped: "gray",
  rejected: "gray",
  retracted: "gray",
  failed: "red",
  error: "red",
};

export function Badge({ children, tone }: { children: string; tone?: keyof typeof tones }) {
  const color = tones[tone ?? statusTone[children] ?? "gray"];
  return (
    <span className={`inline-block rounded-[4px] px-1.5 py-0.5 font-mono text-[10.5px] font-medium uppercase tracking-[0.06em] ring-1 ring-inset ${color}`}>
      {children}
    </span>
  );
}

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[26px] font-semibold leading-tight tracking-[-0.02em] text-stone-900">{title}</h1>
        {subtitle && <p className="mt-1.5 max-w-2xl text-sm text-stone-500">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function Notice({ tone = "red", children }: { tone?: "red" | "amber" | "green"; children: ReactNode }) {
  if (!children) return null;
  return (
    <div role={tone === "red" ? "alert" : "status"} className={`mb-4 rounded-[6px] px-3 py-2 text-sm ring-1 ring-inset ${tones[tone]}`}>
      {children}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-[8px] border border-dashed border-stone-300 bg-white/50 p-10 text-center text-sm text-stone-500">{children}</p>;
}

/** A number with its label, the building block of every overview. */
export function Stat({ label, value, hint, accent = false }: { label: string; value: ReactNode; hint?: ReactNode; accent?: boolean }) {
  return (
    <div className={`relative overflow-hidden rounded-[8px] border bg-white p-4 ${accent ? "border-brand-300" : "border-stone-300/70"}`}>
      {accent && <span aria-hidden="true" className="absolute inset-x-0 top-0 h-0.5 bg-brand-500" />}
      <div className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-stone-500">{label}</div>
      <div className="tabular mt-2 text-[28px] font-semibold leading-none tracking-[-0.02em] text-stone-900">{value}</div>
      {hint && <div className="mt-2 text-xs text-stone-500">{hint}</div>}
    </div>
  );
}
