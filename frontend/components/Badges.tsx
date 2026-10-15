"use client";

import type { EventType, ProductState } from "@/lib/api";

const STATE_STYLE: Record<ProductState, { label: string; className: string; dot: string }> = {
  ON_SHELF: {
    label: "ON SHELF",
    className: "border-teal-200 bg-teal-100 text-teal-700",
    dot: "bg-teal-500",
  },
  LIFTING: {
    label: "LIFTING",
    className: "border-amber-200 bg-amber-200/60 text-amber-300",
    dot: "bg-amber-500",
  },
  IN_HAND: {
    label: "IN HAND",
    className: "border-[#EEDBCF] bg-[#FBEEE7] text-[#A85F3C]",
    dot: "bg-state-hand",
  },
  RETURNING: {
    label: "RETURNING",
    className: "border-[#DCE6F6] bg-[#EEF3FC] text-[#4A6BA5]",
    dot: "bg-state-returning",
  },
  IN_BASKET: {
    label: "IN BASKET",
    className: "border-[#E0DDF6] bg-[#F1EFFC] text-[#5F58AE]",
    dot: "bg-state-basket",
  },
  LOST: {
    label: "LOST",
    className: "border-rose-200 bg-rose-200/50 text-rose-300",
    dot: "bg-state-lost",
  },
};

const EVENT_STYLE: Record<string, string> = {
  TOUCH: "border-lavender-300 bg-lavender-100 text-navy-600",
  PICKED_UP: "border-[#EEDBCF] bg-[#FBEEE7] text-[#A85F3C]",
  PUT_BACK: "border-[#DCE6F6] bg-[#EEF3FC] text-[#4A6BA5]",
  PLACED_IN_BASKET: "border-[#E0DDF6] bg-[#F1EFFC] text-[#5F58AE]",
  CHECKED_OUT: "border-teal-200 bg-mint-200/70 text-teal-700",
  TRACK_LOST: "border-rose-200 bg-rose-200/50 text-rose-300",
  ALERT_RAISED: "border-amber-200 bg-amber-200/60 text-amber-300",
};

const FALLBACK_EVENT = "border-lavender-300 bg-lavender-100 text-navy-600";

export function StateBadge({ state, pulse }: { state: ProductState; pulse?: boolean }) {
  const s = STATE_STYLE[state] ?? STATE_STYLE.ON_SHELF;
  return (
    <span className={`chip whitespace-nowrap ${s.className} ${pulse ? "animate-pulse" : ""}`}>
      <span className={`mr-1 inline-block h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}

export function EventBadge({ type }: { type: EventType | string }) {
  return (
    <span className={`chip whitespace-nowrap ${EVENT_STYLE[type] ?? FALLBACK_EVENT}`}>
      {type}
    </span>
  );
}
