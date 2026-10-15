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
      <div className="space-y-2 p-4">
        {(data?.state_machine.transitions ?? []).map((t, i) => (
          <div key={i} className="rounded-2xl border border-lavender-200 bg-lavender-100/70 p-3">
            <div className="flex items-center gap-2 font-mono text-[10px]">
              <span className="rounded-full bg-white px-2 py-0.5 text-navy-700">{t.from}</span>
              <span className="text-navy-400">&rarr;</span>
              <span className="rounded-full bg-teal-500 px-2 py-0.5 font-semibold text-white">
                {t.to}
              </span>
            </div>
            <div className="mt-1.5 text-[10px] leading-snug text-navy-500">{t.when}</div>
          </div>
        ))}
        {(data?.state_machine.always_events ?? []).map((e, i) => (
          <div
            key={`a${i}`}
            className="rounded-2xl border border-lavender-200 bg-lavender-100/70 p-3"
          >
            <div className="inline-block rounded-full bg-navy-800 px-2 py-0.5 font-mono text-[10px] text-mint-200">
              {e.event}
            </div>
            <div className="mt-1.5 text-[10px] leading-snug text-navy-500">{e.when}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
