"use client";

import { useState } from "react";
import { api } from "@/lib/api";

/**
 * Fallback basket zone, used only when the YOLO model has no basket class of
 * its own. Normalised [x, y, w, h] in 0..1.
 */
export default function BasketRoiPanel({
  roi,
  onSaved,
}: {
  roi?: string | null;
  onSaved?: () => void;
}) {
  const [box, setBox] = useState({ x: 0.7, y: 0.55, w: 0.28, h: 0.42 });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const set = (k: keyof typeof box) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setBox((b) => ({ ...b, [k]: Math.min(1, Math.max(0, Number(e.target.value))) }));

  async function save(roi: number[] | null) {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      await api.setBasketRoi(roi);
      setMsg(roi ? "Fallback basket zone saved." : "Fallback basket zone cleared.");
      onSaved?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <span className="panel-title">Basket zone (fallback)</span>
        <span className="font-mono text-[10px] text-slate-500">{roi ?? "yolo"}</span>
      </div>
      <div className="space-y-2.5 p-3">
        <p className="text-[10px] leading-relaxed text-slate-500">
          A basket class in YOLO is always preferred. Set this normalised region only when the
          model cannot detect the basket itself.
        </p>
        <div className="grid grid-cols-2 gap-2">
          {(["x", "y", "w", "h"] as const).map((k) => (
            <label key={k} className="block">
              <span className="label">{k}</span>
              <input
                type="number"
                step={0.01}
                min={0}
                max={1}
                className="field"
                value={box[k]}
                onChange={set(k)}
              />
            </label>
          ))}
        </div>
        <div className="flex gap-2 pt-1">
          <button
            className="btn btn-primary"
            disabled={busy}
            onClick={() => save([box.x, box.y, box.w, box.h])}
          >
            {busy ? "Saving..." : "Save region"}
          </button>
          <button className="btn" disabled={busy} onClick={() => save(null)}>
            Use YOLO only
          </button>
        </div>
        {msg && <div className="font-mono text-[10px] text-emerald-400">{msg}</div>}
        {err && <div className="font-mono text-[10px] text-rose-400">{err}</div>}
      </div>
    </section>
  );
}
