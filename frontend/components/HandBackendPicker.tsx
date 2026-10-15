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
        <span className="meta">active: {data?.active ?? "-"}</span>
      </div>
      <div className="space-y-3 p-4">
        <p className="text-[10px] leading-relaxed text-navy-500">
          The touch signal gates <span className="font-mono text-navy-700">LIFTING</span>, so if the
          hand model cannot see anything no product ever leaves{" "}
          <span className="font-mono text-navy-700">ON_SHELF</span>.
        </p>

        <div className="space-y-2">
          {(data?.options ?? []).map((o) => (
            <button
              key={o.key}
              onClick={() => choose(o.key)}
              disabled={busy !== null}
              className={`block w-full rounded-2xl border px-3 py-2.5 text-left transition ${
                data?.configured === o.key
                  ? "border-teal-300 bg-mint-200/70 shadow-soft"
                  : "border-lavender-200 bg-white hover:border-teal-200 hover:bg-lavender-100"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-[11px] font-semibold text-navy-800">{o.label}</span>
                {busy === o.key && <span className="meta">...</span>}
                {data?.configured === o.key && (
                  <span className="font-mono text-[9px] text-teal-600">selected</span>
                )}
              </div>
              <div className="mt-1 text-[10px] leading-snug text-navy-500">{o.description}</div>
            </button>
          ))}
        </div>

        {data && !data.hand_model_present && (
          <div className="rounded-2xl border border-amber-200 bg-amber-200/50 px-3 py-2 text-[10px] text-amber-300">
            The handtracking ONNX model is missing - run{" "}
            <span className="font-mono">backend\setup-hand-model.bat</span>.
          </div>
        )}

        {handsBlind && (
          <div className="rounded-2xl border border-rose-200 bg-rose-200/50 px-3 py-2 text-[10px] text-rose-300">
            No hands detected for several seconds. Pickups cannot be confirmed with this backend.
          </div>
        )}

        {err && <div className="font-mono text-[10px] text-rose-300">{err}</div>}
      </div>
    </section>
  );
}
