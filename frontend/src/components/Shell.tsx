"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { Loading } from "@/components/ui";
import { clearToken, getToken } from "@/lib/api";

interface NavItem {
  href: string;
  label: string;
}

interface Module {
  key: string;
  label: string;
  items: NavItem[];
}

const MODULES: Module[] = [
  {
    key: "freelance",
    label: "Freelance",
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
    items: [
      { href: "/jobs", label: "Overview" },
      { href: "/jobs/compose", label: "New application" },
      { href: "/jobs/applications", label: "Applications" },
      { href: "/jobs/prompt", label: "Prompt" },
      { href: "/jobs/profile", label: "Profile & CVs" },
    ],
  },
  {
    key: "outreach",
    label: "Outreach",
    items: [
      { href: "/outreach", label: "Overview" },
      { href: "/outreach/campaigns/new", label: "New campaign" },
      { href: "/outreach/campaigns", label: "Campaigns" },
      { href: "/outreach/templates", label: "Templates" },
      { href: "/outreach/suppressions", label: "Do not contact" },
    ],
  },
  {
    key: "linkedin",
    label: "LinkedIn",
    items: [
      { href: "/linkedin", label: "Posts" },
      { href: "/linkedin/settings", label: "Settings" },
    ],
  },
  {
    key: "system",
    label: "System",
    items: [
      { href: "/email-settings", label: "Email settings" },
      { href: "/logs", label: "Activity log" },
    ],
  },
];

const FREELANCE_ROOTS = ["/queue", "/projects", "/bids", "/prompts", "/profile", "/settings"];

const ICONS: Record<string, string> = {
  freelance: "M3 7h18v12H3zM8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12h18",
  jobs: "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6",
  outreach: "M3 6h18v12H3zM3 7l9 7 9-7",
  linkedin: "M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM8 10v6M8 7.5v.01M12 16v-6M12 12.5c0-1.5 1-2.5 2.5-2.5S17 11 17 12.5V16",
  system: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4",
};

function Icon({ name, className = "h-[18px] w-[18px]" }: { name: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={className} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d={ICONS[name]} />
    </svg>
  );
}

function isActive(href: string, pathname: string): boolean {
  if (href === "/" || href === "/jobs" || href === "/outreach" || href === "/linkedin") return pathname === href;
  // "New campaign" lives under /outreach/campaigns, so the list must not light up for it.
  if (href === "/outreach/campaigns") return pathname === href || (pathname.startsWith(`${href}/`) && !pathname.startsWith(`${href}/new`));
  return pathname === href || pathname.startsWith(`${href}/`);
}

function currentModule(pathname: string): Module {
  const byKey = (key: string) => MODULES.find((m) => m.key === key)!;
  if (pathname.startsWith("/jobs")) return byKey("jobs");
  if (pathname.startsWith("/outreach")) return byKey("outreach");
  if (pathname.startsWith("/linkedin")) return byKey("linkedin");
  if (pathname === "/" || FREELANCE_ROOTS.some((root) => pathname.startsWith(root))) return byKey("freelance");
  return byKey("system");
}

const noopSubscribe = () => () => {};

function Brand() {
  return (
    <div className="flex items-center gap-3">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/codevryn-mark.png" alt="" width={32} height={32} className="h-8 w-8 rounded-[9px] ring-1 ring-white/10" />
      <div className="leading-tight">
        <div className="text-[15px] font-semibold tracking-tight text-white">Worklane</div>
        <div className="text-[11px] text-graphite-400">Codevryn workspace</div>
      </div>
    </div>
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
  // Sections the user opened or closed by hand; the one that holds the current page is open unless closed on purpose.
  const [toggled, setToggled] = useState<Record<string, boolean>>({});

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
  const isOpen = (m: Module) => toggled[m.key] ?? m.key === section.key;

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="flex shrink-0 flex-col bg-graphite-900 text-graphite-300 md:sticky md:top-0 md:h-screen md:w-[17rem]">
        <div className="flex items-center justify-between px-4 py-3.5 md:px-5 md:py-5">
          <Brand />
          <button type="button" onClick={() => signOut(router)} className="text-[12px] font-medium text-graphite-400 hover:text-white md:hidden">
            Sign out
          </button>
        </div>

        {/* Phone: the sections as tabs, then the pages of the current one. */}
        <nav aria-label="Sections" className="flex gap-1.5 overflow-x-auto px-3 pb-2 md:hidden">
          {MODULES.map((m) => (
            <Link
              key={m.key}
              href={m.items[0].href}
              className={`flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-medium ${
                m.key === section.key ? "bg-white text-graphite-900" : "bg-graphite-800 text-graphite-300"
              }`}
            >
              <Icon name={m.key} className="h-4 w-4" />
              {m.label}
            </Link>
          ))}
        </nav>
        <nav aria-label="Pages" className="flex gap-1 overflow-x-auto border-t border-graphite-800 px-3 py-2 md:hidden">
          {section.items.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive(item.href, pathname) ? "page" : undefined}
              className={`shrink-0 rounded-[8px] px-2.5 py-1.5 text-[13px] font-medium ${isActive(item.href, pathname) ? "bg-graphite-800 text-white" : "text-graphite-300"}`}
            >
              {item.label}
            </Link>
          ))}
        </nav>

        {/* Desktop: one line per section; only the open section shows its pages. */}
        <nav aria-label="Main" className="hidden flex-1 space-y-1 overflow-y-auto px-3 pb-4 md:block">
          {MODULES.map((m) => {
            const open = isOpen(m);
            const current = m.key === section.key;
            return (
              <div key={m.key}>
                <button
                  type="button"
                  aria-expanded={open}
                  onClick={() => setToggled({ ...toggled, [m.key]: !open })}
                  className={`flex w-full items-center gap-3 rounded-[10px] px-3 py-2 text-left text-[14px] font-medium transition-colors ${
                    current ? "text-white" : "text-graphite-300 hover:bg-graphite-800/60 hover:text-white"
                  }`}
                >
                  <Icon name={m.key} className={`h-[18px] w-[18px] ${current ? "text-brand-400" : "text-graphite-400"}`} />
                  <span className="flex-1">{m.label}</span>
                  <svg viewBox="0 0 16 16" aria-hidden="true" className={`h-3.5 w-3.5 text-graphite-500 transition-transform ${open ? "rotate-90" : ""}`} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M6 3l5 5-5 5" />
                  </svg>
                </button>
                {open && (
                  <ul className="mb-1 ml-[1.35rem] mt-0.5 space-y-0.5 border-l border-graphite-800 pl-3">
                    {m.items.map((item) => {
                      const active = isActive(item.href, pathname);
                      return (
                        <li key={item.href}>
                          <Link
                            href={item.href}
                            aria-current={active ? "page" : undefined}
                            className={`block rounded-[8px] px-2.5 py-1.5 text-[13px] transition-colors ${
                              active ? "bg-graphite-800 font-medium text-white" : "text-graphite-400 hover:bg-graphite-800/50 hover:text-white"
                            }`}
                          >
                            {item.label}
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            );
          })}
        </nav>

        <div className="hidden border-t border-graphite-800 p-3 md:block">
          <button
            type="button"
            onClick={() => signOut(router)}
            className="flex w-full items-center gap-3 rounded-[10px] px-3 py-2 text-left text-[13px] font-medium text-graphite-400 hover:bg-graphite-800/60 hover:text-white"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h4M16 8l4 4-4 4M20 12H9" />
            </svg>
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-12 items-center border-b border-stone-200 bg-canvas/80 px-4 backdrop-blur md:px-8">
          <div className="flex min-w-0 items-center gap-2 text-[13px] text-stone-500">
            <span>{section.label}</span>
            {page && (
              <>
                <span aria-hidden="true" className="text-stone-300">
                  /
                </span>
                <span className="truncate font-medium text-stone-800">{page.label}</span>
              </>
            )}
          </div>
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
