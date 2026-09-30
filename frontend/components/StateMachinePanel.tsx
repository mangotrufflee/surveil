"use client";

import { usePolling } from "@/lib/usePolling";
import { api, type AppConfig } from "@/lib/api";

export default function StateMachinePanel() {
  const { data } = usePolling<AppConfig>(() => api.config(), 0);

  return (
    <section className="panel">
      <div className="panel-head">
        <span className="panel-title">State machine</span>
      </div>
      <div className="space-y-1 p-3">
        {(data?.state_machine.transitions ?? []).map((t, i) => (
          <div key={i} className="rounded-md border border-ink-700 bg-ink-850/50 p-2">
            <div className="flex items-center gap-1.5 font-mono text-[10px]">
              <span className="text-slate-300">{t.from}</span>
              <span className="text-slate-600">-&gt;</span>
              <span className="text-emerald-400">{t.to}</span>
            </div>
            <div className="mt-0.5 text-[10px] leading-snug text-slate-500">{t.when}</div>
          </div>
        ))}
        {(data?.state_machine.always_events ?? []).map((e, i) => (
          <div key={`a${i}`} className="rounded-md border border-ink-700 bg-ink-850/50 p-2">
            <div className="font-mono text-[10px] text-slate-300">{e.event}</div>
            <div className="mt-0.5 text-[10px] leading-snug text-slate-500">{e.when}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
