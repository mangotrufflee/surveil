"use client";

import type { EventType, ProductState } from "@/lib/api";

const STATE_STYLE: Record<ProductState, { label: string; className: string; dot: string }> = {
  ON_SHELF: {
    label: "ON SHELF",
    className: "border-state-shelf/40 bg-state-shelf/10 text-state-shelf",
    dot: "bg-state-shelf",
  },
  LIFTING: {
    label: "LIFTING",
    className: "border-state-lifting/40 bg-state-lifting/10 text-state-lifting",
    dot: "bg-state-lifting",
  },
  IN_HAND: {
    label: "IN HAND",
    className: "border-state-hand/40 bg-state-hand/10 text-state-hand",
    dot: "bg-state-hand",
  },
  RETURNING: {
    label: "RETURNING",
    className: "border-state-returning/40 bg-state-returning/10 text-state-returning",
    dot: "bg-state-returning",
  },
  IN_BASKET: {
    label: "IN BASKET",
    className: "border-state-basket/40 bg-state-basket/10 text-state-basket",
    dot: "bg-state-basket",
  },
  LOST: {
    label: "LOST",
    className: "border-state-lost/40 bg-state-lost/10 text-state-lost",
    dot: "bg-state-lost",
  },
};

const EVENT_STYLE: Record<string, string> = {
  TOUCH: "border-slate-500/40 bg-slate-500/10 text-slate-300",
  PICKED_UP: "border-state-hand/40 bg-state-hand/10 text-state-hand",
  PUT_BACK: "border-state-returning/40 bg-state-returning/10 text-state-returning",
  PLACED_IN_BASKET: "border-state-basket/40 bg-state-basket/10 text-state-basket",
  CHECKED_OUT: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  TRACK_LOST: "border-state-lost/40 bg-state-lost/10 text-state-lost",
  ALERT_RAISED: "border-amber-500/40 bg-amber-500/10 text-amber-300",
};

export function StateBadge({ state, pulse }: { state: ProductState; pulse?: boolean }) {
  const s = STATE_STYLE[state] ?? STATE_STYLE.ON_SHELF;
  return (
    <span className={`chip ${s.className} ${pulse ? "animate-pulse" : ""}`}>
      <span className={`mr-1 inline-block h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}

export function EventBadge({ type }: { type: EventType | string }) {
  return (
    <span className={`chip ${EVENT_STYLE[type] ?? "border-ink-600 bg-ink-800 text-slate-300"}`}>
      {type}
    </span>
  );
}
