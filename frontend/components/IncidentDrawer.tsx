"use client";

import { useEffect } from "react";
import { ago, clock, stamp } from "@/lib/format";
import { EventBadge, StateBadge } from "@/components/Badges";
import type { Alert, LedgerEvent, PendingRow } from "@/lib/api";

export interface IncidentTarget {
  type: "alert" | "pending" | "event";
  alert?: Alert;
  pending?: PendingRow;
  event?: LedgerEvent;
}

interface IncidentDrawerProps {
  target: IncidentTarget | null;
  onClose: () => void;
  onCheckout: (item: {
    product_id: string;
    product_name: string;
    track_id: number;
    session_id?: string | null;
    event_uid?: string | null;
  }) => Promise<void>;
  onResolve: (uid: string, reason: string) => Promise<void>;
}

export default function IncidentDrawer({
  target,
  onClose,
  onCheckout,
  onResolve,
}: IncidentDrawerProps) {
  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  if (!target) return null;

  const item = target.alert || target.pending || target.event;
  if (!item) return null;

  const productName = item.product_name ?? "Product";
  const productId = item.product_id ?? "unknown";
  const trackId = item.track_id ?? 0;
  const ts = item.ts ?? Date.now() / 1000;
  const sessionId = item.session_id ?? "unknown";
  const handId = target.pending?.hand_id ?? target.event?.hand_id ?? null;
  const eventUid = item.event_uid;
  const isAlert = target.type === "alert";
  const alertSeverity = target.alert?.severity ?? "medium";

  const handleExportJson = () => {
    const dataStr =
      "data:text/json;charset=utf-8," +
      encodeURIComponent(JSON.stringify({ ...target, exportedAt: new Date().toISOString() }, null, 2));
    const dlAnchorElem = document.createElement("a");
    dlAnchorElem.setAttribute("href", dataStr);
    dlAnchorElem.setAttribute("download", `incident_${productId}_${Date.now()}.json`);
    dlAnchorElem.click();
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-navy-950/40 backdrop-blur-sm transition-opacity">
      {/* Backdrop click to close */}
      <div className="flex-1" onClick={onClose} />

      {/* Slide-over panel */}
      <div className="relative flex h-full w-full max-w-md flex-col bg-white shadow-2xl border-l border-lavender-200">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-lavender-200 bg-lavender-100/80 px-6 py-4">
          <div className="flex items-center gap-2.5">
            <span
              className={`h-3 w-3 rounded-full ${
                isAlert
                  ? alertSeverity === "high"
                    ? "bg-rose-500 animate-ping"
                    : "bg-amber-500"
                  : "bg-teal-500"
              }`}
            />
            <div>
              <h2 className="text-base font-bold text-navy-800">Incident Review</h2>
              <p className="text-[10px] font-mono uppercase tracking-wider text-navy-400">
                {target.type.toUpperCase()} · ID #{trackId}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-white text-navy-500 shadow-sm hover:bg-lavender-200"
          >
            ✕
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Main Product Card */}
          <div className="rounded-2xl border border-lavender-200 bg-lavender-50 p-4">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h3 className="text-lg font-bold text-navy-800">{productName}</h3>
                <span className="font-mono text-xs text-navy-500">{productId}</span>
              </div>
              {target.event?.type && <EventBadge type={target.event.type} />}
              {target.pending && (
                <span className="chip border-purple-200 bg-purple-100 text-purple-700">
                  {target.pending.reason}
                </span>
              )}
            </div>

            <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-xl bg-white p-2.5 border border-lavender-200">
                <span className="text-[10px] uppercase font-semibold text-navy-400">
                  ByteTrack ID
                </span>
                <div className="font-mono font-bold text-navy-800">#{trackId}</div>
              </div>
              <div className="rounded-xl bg-white p-2.5 border border-lavender-200">
                <span className="text-[10px] uppercase font-semibold text-navy-400">
                  Customer Hand
                </span>
                <div className="font-mono font-bold text-navy-800">
                  {handId != null ? `Hand #${handId}` : "None"}
                </div>
              </div>
              <div className="rounded-xl bg-white p-2.5 border border-lavender-200">
                <span className="text-[10px] uppercase font-semibold text-navy-400">
                  Timestamp
                </span>
                <div className="font-mono text-navy-700">{clock(ts)}</div>
              </div>
              <div className="rounded-xl bg-white p-2.5 border border-lavender-200">
                <span className="text-[10px] uppercase font-semibold text-navy-400">
                  Elapsed Time
                </span>
                <div className="font-mono text-navy-700">{ago((Date.now() / 1000) - ts)} ago</div>
              </div>
            </div>
          </div>

          {/* Alert Message if present */}
          {target.alert && (
            <div className="rounded-2xl border border-rose-300 bg-rose-50 p-4 text-rose-800">
              <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-rose-700">
                <span>⚠ Alert: {target.alert.kind}</span>
                <span className="ml-auto rounded bg-rose-200 px-2 py-0.5 text-[10px]">
                  {target.alert.severity}
                </span>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-rose-900">
                {target.alert.message}
              </p>
            </div>
          )}

          {/* Chronological Journey Steps */}
          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-navy-500 mb-3">
              Journey Timeline
            </h4>
            <div className="space-y-3 relative before:absolute before:inset-0 before:left-3.5 before:w-0.5 before:bg-lavender-200">
              <div className="relative flex items-start gap-3 pl-1">
                <div className="h-6 w-6 rounded-full bg-teal-500 text-white flex items-center justify-center text-[10px] font-bold z-10">
                  1
                </div>
                <div className="text-xs">
                  <div className="font-semibold text-navy-800">Initialized on Shelf</div>
                  <div className="text-[10px] font-mono text-navy-400">
                    Settled anchor position confirmed
                  </div>
                </div>
              </div>

              <div className="relative flex items-start gap-3 pl-1">
                <div className="h-6 w-6 rounded-full bg-amber-500 text-white flex items-center justify-center text-[10px] font-bold z-10">
                  2
                </div>
                <div className="text-xs">
                  <div className="font-semibold text-navy-800">Hand Contact & Lift</div>
                  <div className="text-[10px] font-mono text-navy-400">
                    Displaced past threshold with hand overlap
                  </div>
                </div>
              </div>

              <div className="relative flex items-start gap-3 pl-1">
                <div className="h-6 w-6 rounded-full bg-purple-500 text-white flex items-center justify-center text-[10px] font-bold z-10">
                  3
                </div>
                <div className="text-xs">
                  <div className="font-semibold text-navy-800">
                    {target.pending?.reason === "in_basket"
                      ? "Placed into Shopping Basket"
                      : "Carried in Hand / Transport"}
                  </div>
                  <div className="text-[10px] font-mono text-navy-400">
                    Session {sessionId}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Action Footer */}
        <div className="border-t border-lavender-200 bg-lavender-50 p-4 space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              className="btn btn-primary justify-center !py-2 !text-xs"
              onClick={async () => {
                await onCheckout({
                  product_id: productId,
                  product_name: productName,
                  track_id: trackId,
                  session_id: sessionId,
                  event_uid: eventUid,
                });
                onClose();
              }}
            >
              ✓ Mark Paid / Sold
            </button>
            <button
              type="button"
              className="btn justify-center !py-2 !text-xs"
              onClick={async () => {
                if (eventUid) {
                  await onResolve(eventUid, "returned to shelf");
                }
                onClose();
              }}
            >
              ↩ Put Back on Shelf
            </button>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              className="btn justify-center !py-1.5 !text-[11px] text-navy-600"
              onClick={async () => {
                if (eventUid) {
                  await onResolve(eventUid, "dismissed as false alarm");
                }
                onClose();
              }}
            >
              Dismiss False Alarm
            </button>
            <button
              type="button"
              className="btn justify-center !py-1.5 !text-[11px] text-navy-600"
              onClick={handleExportJson}
            >
              Export JSON Report
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
