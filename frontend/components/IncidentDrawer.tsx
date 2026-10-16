"use client";

import { useEffect, useState } from "react";
import { ago, clock, stamp } from "@/lib/format";
import { EventBadge, StateBadge } from "@/components/Badges";
import { api, type Alert, type LedgerEvent, type PendingRow, type ProductState } from "@/lib/api";

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
    basket_track_id?: number | null;
  }) => Promise<void>;
  onResolve: (uid: string, reason: string) => Promise<void>;
}

export default function IncidentDrawer({
  target,
  onClose,
  onCheckout,
  onResolve,
}: IncidentDrawerProps) {
  const [productHistory, setProductHistory] = useState<LedgerEvent[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [copied, setCopied] = useState(false);
  const [busyAction, setBusyAction] = useState<string | null>(null);

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  // Fetch real chronological ledger events for this product_id
  useEffect(() => {
    if (!target) {
      setProductHistory([]);
      return;
    }
    const item = target.alert || target.pending || target.event;
    const pid = item?.product_id;
    if (!pid) return;

    let alive = true;
    setLoadingHistory(true);

    api
      .events({ product_id: pid, limit: 50 })
      .then((res) => {
        if (alive) {
          // Sort oldest to newest for chronological journey
          const sorted = [...(res.events ?? [])].sort((a, b) => a.ts - b.ts);
          setProductHistory(sorted);
        }
      })
      .catch((err) => {
        console.warn("Could not fetch product event history:", err);
      })
      .finally(() => {
        if (alive) setLoadingHistory(false);
      });

    return () => {
      alive = false;
    };
  }, [target]);

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

  // Extra details from pending or event
  const basketTrackId =
    target.pending?.basket_track_id ?? target.event?.basket_track_id ?? null;
  const liveState =
    target.pending?.live_state ?? (target.event?.state as ProductState) ?? null;
  const dwellMs = target.event?.dwell_ms ?? null;
  const displacement =
    typeof target.event?.meta?.displacement_px === "number"
      ? target.event.meta.displacement_px
      : null;
  const inferred = target.pending?.inferred === 1 || target.event?.inferred === 1;
  const isResolved = target.event?.resolved === 1;
  const resolution = target.event?.resolution;

  const handleCopyId = () => {
    navigator.clipboard.writeText(productId);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleExportJson = () => {
    const reportData = {
      incidentType: target.type,
      exportedAt: new Date().toISOString(),
      itemDetails: {
        productName,
        productId,
        trackId,
        sessionId,
        handId,
        basketTrackId,
        liveState,
        dwellMs,
        displacement,
        inferred,
        eventUid,
      },
      alertDetails: target.alert ?? null,
      chronologicalJourney: productHistory,
    };

    const dataStr =
      "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(reportData, null, 2));
    const dlAnchorElem = document.createElement("a");
    dlAnchorElem.setAttribute("href", dataStr);
    dlAnchorElem.setAttribute("download", `incident_report_${productId}_${Date.now()}.json`);
    document.body.appendChild(dlAnchorElem);
    dlAnchorElem.click();
    document.body.removeChild(dlAnchorElem);
  };

  const executeAction = async (label: string, fn: () => Promise<void>) => {
    setBusyAction(label);
    try {
      await fn();
      onClose();
    } catch (err) {
      console.error(`Failed ${label}:`, err);
    } finally {
      setBusyAction(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-navy-950/40 backdrop-blur-sm transition-opacity">
      {/* Backdrop click to close */}
      <div className="flex-1" onClick={onClose} />

      {/* Slide-over panel */}
      <div className="relative flex h-full w-full max-w-lg flex-col bg-white shadow-2xl border-l border-lavender-200">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-lavender-200 bg-lavender-100/90 px-6 py-4">
          <div className="flex items-center gap-3">
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
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-navy-800">Incident Review</h2>
                <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-mono font-bold text-navy-600 border border-lavender-300">
                  {target.type.toUpperCase()}
                </span>
              </div>
              <p className="text-[10px] font-mono text-navy-400 mt-0.5">
                Target track #{trackId} · Session {sessionId}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-white text-navy-500 shadow-sm hover:bg-lavender-200 transition"
            title="Close drawer (ESC)"
          >
            ✕
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-5">
          {/* Main Product Card */}
          <div className="rounded-2xl border border-lavender-200 bg-lavender-50/70 p-4 shadow-xs">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-lg font-bold text-navy-800 leading-tight">{productName}</h3>
                <div className="flex items-center gap-2 mt-1">
                  <span className="font-mono text-xs text-navy-500 font-semibold">{productId}</span>
                  <button
                    type="button"
                    onClick={handleCopyId}
                    className="text-[10px] text-teal-600 hover:text-teal-800 underline"
                  >
                    {copied ? "✓ Copied" : "Copy ID"}
                  </button>
                </div>
              </div>

              <div className="flex flex-col items-end gap-1.5">
                {liveState && <StateBadge state={liveState} />}
                {target.event?.type && <EventBadge type={target.event.type} />}
                {target.pending && (
                  <span className="chip border-purple-200 bg-purple-100 text-purple-700 font-mono text-[9px]">
                    {target.pending.reason}
                  </span>
                )}
              </div>
            </div>

            {/* Comprehensive Metrics Grid */}
            <div className="mt-4 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
              <div className="rounded-xl bg-white p-2.5 border border-lavender-200">
                <span className="text-[9px] uppercase font-bold text-navy-400 block">
                  ByteTrack ID
                </span>
                <div className="font-mono font-bold text-navy-800">#{trackId}</div>
              </div>
              <div className="rounded-xl bg-white p-2.5 border border-lavender-200">
                <span className="text-[9px] uppercase font-bold text-navy-400 block">
                  Customer Hand
                </span>
                <div className="font-mono font-bold text-navy-800">
                  {handId != null ? `Hand #${handId}` : "None"}
                </div>
              </div>
              <div className="rounded-xl bg-white p-2.5 border border-lavender-200">
                <span className="text-[9px] uppercase font-bold text-navy-400 block">
                  Basket Track
                </span>
                <div className="font-mono font-bold text-navy-800">
                  {basketTrackId != null ? `#${basketTrackId}` : "None"}
                </div>
              </div>
              <div className="rounded-xl bg-white p-2.5 border border-lavender-200">
                <span className="text-[9px] uppercase font-bold text-navy-400 block">
                  Inferred
                </span>
                <div className="font-mono font-bold text-navy-800">
                  {inferred ? "Yes (History)" : "No (Direct)"}
                </div>
              </div>
              <div className="rounded-xl bg-white p-2.5 border border-lavender-200">
                <span className="text-[9px] uppercase font-bold text-navy-400 block">
                  Displacement
                </span>
                <div className="font-mono text-navy-700 font-semibold">
                  {displacement != null ? `${displacement}px` : "-"}
                </div>
              </div>
              <div className="rounded-xl bg-white p-2.5 border border-lavender-200">
                <span className="text-[9px] uppercase font-bold text-navy-400 block">
                  Dwell Time
                </span>
                <div className="font-mono text-navy-700 font-semibold">
                  {dwellMs != null ? `${(dwellMs / 1000).toFixed(1)}s` : "-"}
                </div>
              </div>
              <div className="rounded-xl bg-white p-2.5 border border-lavender-200 col-span-2">
                <span className="text-[9px] uppercase font-bold text-navy-400 block">
                  Incident Time
                </span>
                <div className="font-mono text-navy-700">
                  {clock(ts)} · {ago(Date.now() / 1000 - ts)} ago
                </div>
              </div>
            </div>

            {/* Resolution indicator if resolved */}
            {isResolved && (
              <div className="mt-3 flex items-center gap-2 rounded-xl border border-teal-200 bg-mint-100/70 p-2.5 text-xs text-teal-800">
                <span>✓ Resolved:</span>
                <span className="font-semibold">{resolution || "Resolved by operator"}</span>
              </div>
            )}
          </div>

          {/* Alert Message Banner if opened from an Alert */}
          {target.alert && (
            <div className="rounded-2xl border border-rose-300 bg-rose-50 p-4 text-rose-800 shadow-xs">
              <div className="flex items-center justify-between text-xs font-bold uppercase tracking-wider text-rose-700">
                <div className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-rose-500 animate-pulse" />
                  <span>ALERT: {target.alert.kind}</span>
                </div>
                <span className="rounded bg-rose-200 px-2 py-0.5 text-[10px] font-mono">
                  {target.alert.severity.toUpperCase()}
                </span>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-rose-900 font-medium">
                {target.alert.message}
              </p>
              <div className="mt-2 text-[10px] font-mono text-rose-700">
                Detected at {clock(target.alert.ts)} ({ago(target.alert.age_s)} ago)
              </div>
            </div>
          )}

          {/* Real Chronological Product Journey Breadcrumbs */}
          <div className="rounded-2xl border border-lavender-200 bg-white p-4 shadow-xs">
            <div className="flex items-center justify-between pb-3 border-b border-lavender-100">
              <h4 className="text-xs font-bold uppercase tracking-wider text-navy-700">
                Product Journey Timeline
              </h4>
              <span className="font-mono text-[10px] text-navy-400">
                {loadingHistory ? "Loading..." : `${productHistory.length} events logged`}
              </span>
            </div>

            <div className="mt-4 space-y-4 relative before:absolute before:inset-0 before:left-3.5 before:w-0.5 before:bg-lavender-200">
              {productHistory.map((ev, index) => {
                const isSelected = ev.event_uid === eventUid;
                return (
                  <div key={ev.event_uid || index} className="relative flex items-start gap-3 pl-1">
                    {/* Step number dot */}
                    <div
                      className={`h-6 w-6 rounded-full flex items-center justify-center text-[10px] font-bold z-10 text-white shadow-xs ${
                        ev.type === "CHECKED_OUT"
                          ? "bg-teal-500"
                          : ev.type === "TRACK_LOST"
                            ? "bg-rose-500"
                            : ev.type === "PLACED_IN_BASKET"
                              ? "bg-purple-500"
                              : ev.type === "PICKED_UP"
                                ? "bg-amber-500"
                                : "bg-navy-600"
                      }`}
                    >
                      {index + 1}
                    </div>

                    {/* Step details */}
                    <div
                      className={`flex-1 rounded-xl p-2.5 text-xs border transition ${
                        isSelected
                          ? "border-teal-400 bg-mint-50 shadow-xs"
                          : "border-lavender-100 bg-lavender-50/50"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-1">
                        <EventBadge type={ev.type} />
                        <span className="font-mono text-[10px] text-navy-400">
                          {clock(ev.ts)} ({ago(Date.now() / 1000 - ev.ts)} ago)
                        </span>
                      </div>

                      <div className="mt-1 text-xs font-semibold text-navy-800">
                        {ev.type === "TOUCH" && "Customer touched product on shelf"}
                        {ev.type === "PICKED_UP" && "Lifted from shelf anchor"}
                        {ev.type === "PLACED_IN_BASKET" && "Placed inside shopping basket"}
                        {ev.type === "PUT_BACK" && "Returned to shelf"}
                        {ev.type === "CHECKED_OUT" && "Reconciled & confirmed purchased"}
                        {ev.type === "TRACK_LOST" && "Tracking signal lost — unaccounted item"}
                        {ev.type === "ALERT_RAISED" && "Operator alert raised"}
                      </div>

                      <div className="mt-1 flex flex-wrap gap-2 text-[10px] font-mono text-navy-500">
                        {ev.hand_id != null && <span>hand #{ev.hand_id}</span>}
                        {ev.basket_track_id != null && <span>basket #{ev.basket_track_id}</span>}
                        {typeof ev.meta?.displacement_px === "number" && (
                          <span>moved {ev.meta.displacement_px}px</span>
                        )}
                        {ev.dwell_ms && <span>dwell {(ev.dwell_ms / 1000).toFixed(1)}s</span>}
                        {ev.state && <span>state: {ev.state}</span>}
                      </div>

                      {ev.resolution && (
                        <div className="mt-1 text-[10px] text-teal-700 font-semibold">
                          Resolved: {ev.resolution}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}

              {productHistory.length === 0 && !loadingHistory && (
                <div className="py-6 text-center text-xs text-navy-400">
                  No previous events recorded for this product.
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Action Footer */}
        <div className="border-t border-lavender-200 bg-lavender-50/80 p-4 space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              disabled={busyAction !== null}
              className="btn btn-primary justify-center !py-2 !text-xs font-semibold shadow-sm"
              onClick={() =>
                executeAction("checkout", async () => {
                  await onCheckout({
                    product_id: productId,
                    product_name: productName,
                    track_id: trackId,
                    session_id: sessionId,
                    event_uid: eventUid,
                    basket_track_id: basketTrackId,
                  });
                })
              }
            >
              {busyAction === "checkout" ? "Checking out..." : "✓ Mark Paid / Sold"}
            </button>
            <button
              type="button"
              disabled={busyAction !== null}
              className="btn justify-center !py-2 !text-xs font-semibold shadow-sm"
              onClick={() =>
                executeAction("put_back", async () => {
                  if (eventUid) {
                    await onResolve(eventUid, "returned to shelf");
                  }
                })
              }
            >
              {busyAction === "put_back" ? "Updating..." : "↩ Put Back on Shelf"}
            </button>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              disabled={busyAction !== null}
              className="btn justify-center !py-1.5 !text-[11px] text-navy-600 hover:text-rose-600"
              onClick={() =>
                executeAction("dismiss", async () => {
                  if (eventUid) {
                    await onResolve(eventUid, "dismissed as false alarm");
                  }
                })
              }
            >
              {busyAction === "dismiss" ? "Dismissing..." : "Dismiss False Alarm"}
            </button>
            <button
              type="button"
              className="btn justify-center !py-1.5 !text-[11px] text-navy-600 font-mono"
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
