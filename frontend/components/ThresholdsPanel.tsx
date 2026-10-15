"use client";

import { useState } from "react";
import { api, type Thresholds } from "@/lib/api";

const FIELDS: {
  key: keyof Thresholds;
  label: string;
  hint: string;
  step?: number;
  min?: number;
  max?: number;
}[] = [
  {
    key: "shelf_displacement_px",
    label: "Shelf displacement",
    hint: "px the product must move from its anchor to count as lifted",
    step: 5,
    min: 5,
  },
  {
    key: "settle_frames",
    label: "Anchor settling frames",
    hint: "still frames before the shelf anchor is trusted",
    step: 1,
    min: 1,
  },
  {
    key: "hand_touch_px",
    label: "Hand touch padding",
    hint: "px the product box is grown by when testing hand contact",
    step: 2,
    min: 0,
  },
  {
    key: "lift_confirm_frames",
    label: "Lift confirm frames",
    hint: "consecutive LIFTING frames before PICKED_UP",
    step: 1,
    min: 1,
  },
  {
    key: "return_confirm_frames",
    label: "Return confirm frames",
    hint: "consecutive RETURNING frames before PUT_BACK",
    step: 1,
    min: 1,
  },
  {
    key: "basket_confirm_frames",
    label: "Basket confirm frames",
    hint: "frames inside the basket zone before PLACED_IN_BASKET",
    step: 1,
    min: 1,
  },
  {
    key: "max_missed_frames",
    label: "Track lifetime",
    hint: "frames a track survives without a detection before it is LOST",
    step: 1,
    min: 1,
  },
];

export default function ThresholdsPanel({ onSaved }: { onSaved?: () => void }) {
  const [values, setValues] = useState<Partial<Record<keyof Thresholds, number | boolean>>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      await api.setThresholds(values as Record<string, number | boolean>);
      setValues({});
      setMsg("Thresholds applied to the running pipeline.");
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
        <span className="panel-title">State machine thresholds</span>
        <button className="btn btn-primary" onClick={save} disabled={busy || !Object.keys(values).length}>
          {busy ? "Saving..." : `Apply${Object.keys(values).length ? ` (${Object.keys(values).length})` : ""}`}
        </button>
      </div>
      <div className="space-y-3 p-4">
        {FIELDS.map((f) => (
          <label key={f.key} className="block">
            <span className="label">{f.label}</span>
            <div className="flex items-center gap-3">
              <input
                type="number"
                className="field w-28"
                step={f.step ?? 1}
                min={f.min}
                max={f.max}
                placeholder="server default"
                onChange={(e) => {
                  const v = e.target.value;
                  setValues((prev) => {
                    const next = { ...prev };
                    if (v === "") delete next[f.key];
                    else next[f.key] = Number(v);
                    return next;
                  });
                }}
              />
              <span className="text-[10px] leading-tight text-navy-500">{f.hint}</span>
            </div>
          </label>
        ))}

        <label className="flex items-center gap-2 pt-1">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 accent-[#438D8B]"
            checked={values.mark_lost_state === undefined ? true : Boolean(values.mark_lost_state)}
            onChange={(e) => setValues((p) => ({ ...p, mark_lost_state: e.target.checked }))}
          />
          <span className="text-[10px] uppercase tracking-wider text-navy-500">
            enter the LOST state when a track expires
          </span>
        </label>

        {msg && <div className="font-mono text-[10px] text-teal-600">{msg}</div>}
        {err && <div className="font-mono text-[10px] text-rose-300">{err}</div>}
      </div>
    </section>
  );
}
