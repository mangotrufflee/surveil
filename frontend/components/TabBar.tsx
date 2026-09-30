"use client";

export type TabKey = "live" | "owner";

const TABS: { key: TabKey; label: string; sub: string }[] = [
  { key: "live", label: "Live CCTV Monitor", sub: "Tab 1 - observes" },
  { key: "owner", label: "Shop Owner Dashboard", sub: "Tab 2 - reconciles" },
];

export default function TabBar({
  tab,
  onChange,
}: {
  tab: TabKey;
  onChange: (t: TabKey) => void;
}) {
  return (
    <div className="flex rounded-lg border border-ink-700 bg-ink-900 p-1">
      {TABS.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          aria-current={tab === t.key ? "page" : undefined}
          className={`rounded-md px-3.5 py-1.5 text-left transition ${
            tab === t.key
              ? "bg-ink-700 text-slate-100 shadow"
              : "text-slate-400 hover:bg-ink-850 hover:text-slate-200"
          }`}
        >
          <div className="text-xs font-semibold">{t.label}</div>
          <div className="text-[9px] uppercase tracking-wider opacity-60">{t.sub}</div>
        </button>
      ))}
    </div>
  );
}
