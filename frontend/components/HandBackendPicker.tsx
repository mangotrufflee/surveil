"use client";

import { useState } from "react";
import { api, type HandBackends } from "@/lib/api";
import { usePolling } from "@/lib/usePolling";

export default function HandBackendPicker({
  handsBlind,
  onChanged,
}: {
  handsBlind?: boolean;
  onChanged?: () => void;
}) {
  const { data, refresh } = usePolling<HandBackends>(() => api.handBackends(), 0);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function choose(key: string) {
    setBusy(key);
    setErr(null);
    try {
      await api.setHandBackend(key);
      refresh();
      onChanged?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <span className="panel-title">Hand detection</span>
        <span className="font-mono text-[10px] text-slate-500">active: {data?.active ?? "-"}</span>
      </div>
      <div className="space-y-2 p-3">
        <p className="text-[10px] leading-relaxed text-slate-500">
          The touch signal gates <span className="font-mono text-slate-400">LIFTING</span>, so if the
          hand model cannot see anything no product ever leaves{" "}
          <span className="font-mono text-slate-400">ON_SHELF</span>.
        </p>

        <div className="space-y-1">
          {(data?.options ?? []).map((o) => (
            <button
              key={o.key}
              onClick={() => choose(o.key)}
              disabled={busy !== null}
              className={`block w-full rounded-md border px-2.5 py-1.5 text-left transition ${
                data?.configured === o.key
                  ? "border-emerald-600/60 bg-emerald-600/15"
                  : "border-ink-700 bg-ink-850/60 hover:border-ink-500"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-[11px] text-slate-200">{o.label}</span>
                {busy === o.key && <span className="font-mono text-[9px] text-slate-500">...</span>}
                {data?.configured === o.key && (
                  <span className="font-mono text-[9px] text-emerald-400">selected</span>
                )}
              </div>
              <div className="mt-0.5 text-[10px] leading-snug text-slate-500">{o.description}</div>
            </button>
          ))}
        </div>

        {data && !data.hand_model_present && (
          <div className="rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1.5 text-[10px] text-amber-300">
            The handtracking ONNX model is missing - run{" "}
            <span className="font-mono">backend\setup-hand-model.bat</span>.
          </div>
        )}

        {handsBlind && (
          <div className="rounded border border-rose-500/40 bg-rose-500/10 px-2 py-1.5 text-[10px] text-rose-300">
            No hands detected for several seconds. Pickups cannot be confirmed with this backend.
          </div>
        )}

        {err && <div className="font-mono text-[10px] text-rose-400">{err}</div>}
      </div>
    </section>
  );
}
