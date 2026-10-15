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
    <div className="flex rounded-full border border-lavender-200 bg-lavender-100 p-1">
      {TABS.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          aria-current={tab === t.key ? "page" : undefined}
          className={`rounded-full px-4 py-1.5 text-left transition ${
            tab === t.key
              ? "bg-navy-800 text-white shadow-soft"
              : "text-navy-500 hover:bg-white hover:text-navy-800"
          }`}
        >
          <div className="text-xs font-semibold">{t.label}</div>
          <div className="text-[9px] uppercase tracking-wider opacity-60">{t.sub}</div>
        </button>
      ))}
    </div>
  );
}
