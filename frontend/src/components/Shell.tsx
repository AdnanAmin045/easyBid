"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useSyncExternalStore, type ReactNode } from "react";
import { Loading } from "@/components/ui";
import { clearToken, getToken } from "@/lib/api";

interface NavItem {
  href: string;
  label: string;
}

const MODULES: { key: string; label: string; tag: string; items: NavItem[] }[] = [
  {
    key: "freelance",
    label: "Freelance",
    tag: "FL",
    items: [
      { href: "/", label: "Overview" },
      { href: "/queue", label: "Approval queue" },
      { href: "/projects", label: "Projects" },
      { href: "/bids", label: "Bids" },
      { href: "/prompts", label: "Prompts" },
      { href: "/profile", label: "Profile" },
      { href: "/settings", label: "Settings" },
    ],
  },
  {
    key: "jobs",
    label: "Jobs",
    tag: "JB",
    items: [
      { href: "/jobs", label: "Overview" },
      { href: "/jobs/compose", label: "New application" },
      { href: "/jobs/applications", label: "Applications" },
      { href: "/jobs/prompt", label: "Prompt" },
      { href: "/jobs/profile", label: "Profile & CVs" },
      { href: "/jobs/settings", label: "Settings" },
    ],
  },
  { key: "system", label: "System", tag: "SY", items: [{ href: "/logs", label: "Activity log" }] },
];

const FREELANCE_ROOTS = ["/queue", "/projects", "/bids", "/prompts", "/profile", "/settings"];

function isActive(href: string, pathname: string): boolean {
  if (href === "/" || href === "/jobs") return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}

function currentModule(pathname: string) {
  if (pathname.startsWith("/jobs")) return MODULES[1];
  if (pathname === "/" || FREELANCE_ROOTS.some((root) => pathname.startsWith(root))) return MODULES[0];
  return MODULES[2];
}

const noopSubscribe = () => () => {};

function Mark() {
  return (
    <span aria-hidden="true" className="grid h-7 w-7 place-items-center rounded-[5px] bg-brand-500 text-graphite-950">
      <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="square">
        <path d="M2 4h12M2 8h8M2 12h12" />
      </svg>
    </span>
  );
}

function signOut(router: ReturnType<typeof useRouter>) {
  clearToken();
  router.replace("/login");
}

export default function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  // null on the server and during hydration, then the real value.
  const signedIn = useSyncExternalStore(noopSubscribe, () => Boolean(getToken()), () => null);

  useEffect(() => {
    if (signedIn === false) router.replace("/login");
  }, [signedIn, router]);

  // Session not read yet, or on the way to the login page.
  if (!signedIn) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loading />
      </div>
    );
  }

  const section = currentModule(pathname);
  const page = section.items.find((item) => isActive(item.href, pathname));

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="grid-texture flex shrink-0 flex-col bg-graphite-900 text-graphite-300 md:sticky md:top-0 md:h-screen md:w-60">
        <div className="flex items-center gap-2.5 px-5 py-4 md:py-5">
          <Mark />
          <div className="leading-tight">
            <div className="text-[15px] font-semibold tracking-tight text-white">Worklane</div>
            <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-graphite-400">Operations</div>
          </div>
        </div>

        <nav aria-label="Main" className="flex gap-4 overflow-x-auto px-3 pb-3 md:flex-1 md:flex-col md:gap-6 md:overflow-y-auto md:pb-6">
          {MODULES.map((group) => (
            <div key={group.key} className="shrink-0">
              <div className="mb-1.5 flex items-center gap-2 px-2 font-mono text-[10px] uppercase tracking-[0.16em] text-graphite-500">
                <span className="rounded-[3px] border border-graphite-700 px-1 py-px text-[9px] text-graphite-400">{group.tag}</span>
                {group.label}
              </div>
              <ul className="flex gap-0.5 md:flex-col">
                {group.items.map((item) => {
                  const active = isActive(item.href, pathname);
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        aria-current={active ? "page" : undefined}
                        className={`relative block whitespace-nowrap rounded-[5px] px-2.5 py-1.5 text-[13px] font-medium transition-colors ${
                          active ? "bg-graphite-800 text-white" : "text-graphite-300 hover:bg-graphite-800/60 hover:text-white"
                        }`}
                      >
                        {active && <span aria-hidden="true" className="absolute inset-y-1.5 left-0 hidden w-0.5 rounded-full bg-brand-500 md:block" />}
                        {item.label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        <div className="hidden border-t border-graphite-800 px-3 py-3 md:block">
          <button
            type="button"
            onClick={() => signOut(router)}
            className="w-full rounded-[5px] px-2.5 py-1.5 text-left text-[13px] font-medium text-graphite-400 hover:bg-graphite-800/60 hover:text-white"
          >
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-12 items-center justify-between border-b border-stone-300/70 bg-canvas/90 px-4 backdrop-blur md:px-8">
          <div className="flex min-w-0 items-center gap-2 font-mono text-[11px] uppercase tracking-[0.14em] text-stone-500">
            <span>{section.label}</span>
            {page && (
              <>
                <span aria-hidden="true" className="text-stone-300">
                  /
                </span>
                <span className="truncate text-stone-800">{page.label}</span>
              </>
            )}
          </div>
          <button
            type="button"
            onClick={() => signOut(router)}
            className="font-mono text-[11px] uppercase tracking-[0.14em] text-stone-500 hover:text-stone-900 md:hidden"
          >
            Sign out
          </button>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-7 md:px-8">
          <div key={pathname} className="animate-rise">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
