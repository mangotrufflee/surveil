"use client";

import { useState } from "react";
import TabBar from "@/components/TabBar";
import LiveMonitor from "@/components/LiveMonitor";
import OwnerDashboard from "@/components/OwnerDashboard";

export default function Home() {
  const [tab, setTab] = useState<"live" | "owner">("live");

  return (
    <>
      <header className="sticky top-0 z-20 border-b border-ink-700 bg-ink-950/90 backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-emerald-500/15 text-sm font-bold text-emerald-400">
              SV
            </div>
            <div>
              <h1 className="text-sm font-semibold tracking-tight text-slate-100">surveil</h1>
              <p className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
                product interaction monitoring
              </p>
            </div>
          </div>
          <TabBar tab={tab} onChange={setTab} />
        </div>
      </header>

      <main className="flex-1 px-5 py-5">
        {tab === "live" ? <LiveMonitor /> : <OwnerDashboard />}
      </main>

      <footer className="border-t border-ink-800 px-5 py-3 text-[10px] text-slate-600">
        Tab 1 observes. Tab 2 manages and reconciles. The CV system never decides on its own
        that something was stolen - it surfaces unresolved situations for the owner to review.
      </footer>
    </>
  );
}
