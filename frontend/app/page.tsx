"use client";

import { useState } from "react";
import TabBar from "@/components/TabBar";
import LiveMonitor from "@/components/LiveMonitor";
import OwnerDashboard from "@/components/OwnerDashboard";

export default function Home() {
  const [tab, setTab] = useState<"live" | "owner">("live");

  return (
    <div className="flex flex-col">
      {/* ------------------------------------------------ centered masthead */}
      <header className="px-2 pb-7 pt-12 text-center sm:pt-16">
        <h1 className="text-balance text-4xl font-bold leading-[1.08] tracking-tight text-navy-800 sm:text-5xl">
          Product interaction monitoring
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-sm font-light leading-relaxed text-navy-500 sm:text-base">
          Observe the shelf, confirm every handover, and keep a clean ledger of what left the store.
        </p>
        <div className="mx-auto mt-7 flex h-1.5 w-24 items-center justify-center gap-1.5">
          <span className="h-1.5 w-6 rounded-full bg-teal-500" />
          <span className="h-1.5 w-6 rounded-full bg-mint-400" />
          <span className="h-1.5 w-6 rounded-full bg-lavender-400" />
        </div>
      </header>

      {/* ----------------------------------------------- browser-style shell */}
      <main className="flex flex-1 flex-col overflow-hidden rounded-shell border border-white/70 bg-white/60 shadow-float backdrop-blur-xl">
        {/* window chrome */}
        <div className="flex shrink-0 items-center gap-4 border-b border-lavender-200 bg-navy-800 px-4 py-2.5">
          <div className="flex gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-mint-300/90" />
            <span className="h-2.5 w-2.5 rounded-full bg-teal-300/90" />
            <span className="h-2.5 w-2.5 rounded-full bg-lavender-300/70" />
          </div>
          <div className="hidden flex-1 items-center gap-2 rounded-full bg-white/10 px-3 py-1 sm:flex">
            <span className="h-1.5 w-1.5 rounded-full bg-mint-300" />
            <span className="font-mono text-[10px] tracking-wide text-lavender-200/90">
              surveil / shop-console
            </span>
          </div>
          <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.18em] text-lavender-300/70">
            observes &amp; reconciles
          </span>
        </div>

        {/* app toolbar */}
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-lavender-200 bg-white/70 px-5 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-navy-800 text-[11px] font-bold tracking-tight text-white shadow-soft">
              SV
            </div>
            <div className="leading-tight">
              <p className="text-sm font-semibold tracking-tight text-navy-800">surveil</p>
              <p className="text-[9px] uppercase tracking-[0.18em] text-navy-400">
                product interaction monitoring
              </p>
            </div>
          </div>
          <TabBar tab={tab} onChange={setTab} />
        </div>

        {/* working area */}
        <div className="flex-1 bg-lavender-100/70 p-4 sm:p-5">
          {tab === "live" ? <LiveMonitor /> : <OwnerDashboard />}
        </div>

        <footer className="shrink-0 border-t border-lavender-200 bg-white/70 px-5 py-3 text-[10px] leading-relaxed text-navy-400">
          The CV system never decides on its own that something was stolen &mdash; it surfaces
          unresolved situations for the owner to review.
        </footer>
      </main>
    </div>
  );
}
