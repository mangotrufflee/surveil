"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, STREAM_URL, type LiveSnapshot, type PipelineStatus } from "@/lib/api";
import { usePolling } from "@/lib/usePolling";
import { StateBadge, EventBadge } from "@/components/Badges";
import { ago, clock } from "@/lib/format";
import ThresholdsPanel from "@/components/ThresholdsPanel";
import BasketRoiPicker from "@/components/BasketRoiPicker";
import HandBackendPicker from "@/components/HandBackendPicker";
import StateMachinePanel from "@/components/StateMachinePanel";

export default function LiveMonitor() {
  const { data: snap, error, refresh } = usePolling<LiveSnapshot>(() => api.live(), 400);
  const { data: status, refresh: refreshStatus } = usePolling<PipelineStatus>(
    () => api.status(),
    1500,
  );
  const [streamNonce, setStreamNonce] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [source, setSource] = useState("0");
  const [showSettings, setShowSettings] = useState(false);
  const frameRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (status?.camera_source) setSource(status.camera_source);
  }, [status?.camera_source]);

  const run = useCallback(
    async (label: string, fn: () => Promise<unknown>, restartStream = false) => {
      setBusy(label);
      setActionError(null);
      try {
        await fn();
        refresh();
        refreshStatus();
        if (restartStream) setStreamNonce((n) => n + 1);
      } catch (err) {
        setActionError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(null);
      }
    },
    [refresh, refreshStatus],
  );

  const running = status?.running ?? false;
  const states = snap ? Object.values(snap.states) : [];
  const hands = snap?.hands ?? [];
  const events = (snap?.recent_events ?? []).slice().reverse();

  // The live snapshot reports the zone actually in use, in frame pixels; convert
  // it back to the normalised [x, y, w, h] the picker draws with.
  const liveRoi = ((): [number, number, number, number] | null => {
    if (!snap?.basket_zone || !snap.frame_size) return null;
    const [fw, fh] = snap.frame_size;
    if (!fw || !fh) return null;
    const [x1, y1, x2, y2] = snap.basket_zone;
    return [x1 / fw, y1 / fh, (x2 - x1) / fw, (y2 - y1) / fh];
  })();

  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_390px]">
      {/* ------------------------------------------------------ stream column */}
      <div className="space-y-5">
        <section className="panel overflow-hidden">
          <div className="panel-head">
            <div className="flex flex-wrap items-center gap-3">
              <span className="panel-title">Live CCTV Monitor</span>
              <span
                className={`chip ${
                  running
                    ? "border-teal-200 bg-mint-200/70 text-teal-700"
                    : "border-rose-200 bg-rose-200/50 text-rose-300"
                }`}
              >
                <span
                  className={`mr-1 inline-block h-1.5 w-1.5 rounded-full ${
                    running ? "animate-pulse bg-teal-500" : "bg-rose-400"
                  }`}
                />
                {running ? "STREAMING" : "STOPPED"}
              </span>
              {snap && snap.ignored_count > 0 && (
                <span
                  className="chip border-lavender-300 bg-lavender-100 text-navy-500"
                  title="The person class is counted but never boxed, highlighted or tracked."
                >
                  {snap.ignored_count} {snap.ignored_classes.join("/")} in frame - not tracked
                </span>
              )}
              {snap?.hands_blind && (
                <span
                  className="chip border-rose-200 bg-rose-200/50 text-rose-300"
                  title="Hand detection sees nothing, so no product can leave ON_SHELF. Switch the hand backend in the thresholds panel."
                >
                  no hands detected - pickups cannot be confirmed
                </span>
              )}
            </div>
            <span className="meta hidden sm:block">{status?.session_id ?? "no session"}</span>
          </div>

          <div ref={frameRef} className="bg-navy-900">
            {running ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                key={streamNonce}
                src={STREAM_URL}
                alt="Annotated camera feed with product and hand detections"
                className="block max-h-[68vh] w-full object-contain"
              />
            ) : (
              <div className="flex aspect-video flex-col items-center justify-center gap-2 bg-gradient-to-br from-lavender-100 to-mint-100 text-navy-400">
                <div className="text-sm font-medium text-navy-600">Camera is stopped</div>
                <div className="text-[11px]">Start the pipeline to begin observing.</div>
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-end gap-2 border-t border-lavender-200 bg-lavender-100/60 p-4">
            <div>
              <label className="label" htmlFor="source">
                Video source (camera index or file path)
              </label>
              <input
                id="source"
                className="field w-64"
                value={source}
                onChange={(e) => setSource(e.target.value)}
                placeholder="0"
              />
            </div>
            <button
              className="btn btn-primary"
              disabled={busy !== null || running}
              onClick={() => run("start", () => api.start(source))}
            >
              {busy === "start" ? "Starting..." : "Start"}
            </button>
            <button
              className="btn btn-danger"
              disabled={busy !== null || !running}
              onClick={() => run("stop", () => api.stop(), true)}
            >
              {busy === "stop" ? "Stopping..." : "Stop"}
            </button>
            <button
              className="btn"
              disabled={busy !== null}
              onClick={() => run("restart", () => api.restart(source), true)}
            >
              {busy === "restart" ? "Restarting..." : "Restart"}
            </button>
            <button
              className="btn ml-auto"
              onClick={() => setShowSettings((v) => !v)}
              aria-expanded={showSettings}
            >
              {showSettings ? "Hide" : "Show"} thresholds
            </button>
          </div>
          {actionError && (
            <div className="note border-rose-200 bg-rose-200/40 font-mono text-[11px] text-rose-300">
              {actionError}
            </div>
          )}
        </section>

        {showSettings && (
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <ThresholdsPanel onSaved={() => { refresh(); refreshStatus(); }} />
            <div className="space-y-5">
              <BasketRoiPicker
                frameSize={snap?.frame_size ?? null}
                roi={liveRoi}
                detected={status?.basket_mode === "yolo"}
                disabled={!running}
                onSaved={() => { refresh(); refreshStatus(); }}
              />
              <HandBackendPicker
                handsBlind={snap?.hands_blind}
                onChanged={refreshStatus}
              />
              <StateMachinePanel />
            </div>
          </div>
        )}
      </div>

      {/* -------------------------------------------------------- side column */}
      <div className="space-y-5">
        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">Product states</span>
            <span className="meta">{states.length} tracked</span>
          </div>
          <div className="max-h-[38vh] space-y-2 overflow-y-auto p-3">
            {states.length === 0 && <Empty text="No products on the shelf yet." />}
            {states.map((s) => {
              const t = s.state;
              const busy =
                t === "LIFTING" ||
                t === "IN_HAND" ||
                t === "RETURNING" ||
                t === "IN_BASKET";
              const progress =
                t === "LIFTING"
                  ? { have: s.lift_frames, need: snap?.thresholds.lift_confirm_frames ?? 5 }
                  : t === "RETURNING"
                    ? { have: s.return_frames, need: snap?.thresholds.return_confirm_frames ?? 5 }
                    : t === "IN_BASKET"
                      ? { have: s.basket_frames, need: snap?.thresholds.basket_confirm_frames ?? 4 }
                      : null;
              return (
                <div
                  key={s.track_id}
                  className="rounded-2xl border border-lavender-200 bg-lavender-100/70 p-3"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="truncate text-xs font-medium text-navy-800">
                        {s.product_name}
                      </span>
                      <span className="meta">#{s.track_id}</span>
                    </div>
                    <StateBadge state={t} pulse={busy} />
                  </div>

                  <div className="mt-2 flex flex-wrap gap-1.5 text-[9px] uppercase tracking-wider">
                    {!s.anchor_confirmed && (
                      <span className="chip border-lavender-300 bg-white text-navy-500">
                        settling {s.settle_frames}/{snap?.thresholds.settle_frames ?? 15}
                      </span>
                    )}
                    {s.touching && (
                      <span className="chip border-[#EEDBCF] bg-[#FBEEE7] text-[#A85F3C]">
                        hand {s.hand_id ?? "-"}
                      </span>
                    )}
                    <span
                      className={`chip ${
                        s.displaced
                          ? "border-amber-200 bg-amber-200/60 text-amber-300"
                          : "border-lavender-300 bg-white text-navy-500"
                      }`}
                    >
                      {s.displacement_px.toFixed(0)}px / {snap?.thresholds.shelf_displacement_px ?? 60}px
                    </span>
                    {s.basket_overlap > 0 && (
                      <span className="chip border-[#E0DDF6] bg-[#F1EFFC] text-[#5F58AE]">
                        basket {(s.basket_overlap * 100).toFixed(0)}%
                      </span>
                    )}
                    <span className="chip border-lavender-300 bg-white text-navy-500">
                      age {ago(s.age_s)}
                    </span>
                  </div>

                  {progress && (
                    <div className="mt-2.5">
                      <div className="h-1.5 overflow-hidden rounded-full bg-lavender-200">
                        <div
                          className="h-full rounded-full bg-teal-500 transition-all"
                          style={{
                            width: `${Math.min(100, (progress.have / Math.max(1, progress.need)) * 100)}%`,
                          }}
                        />
                      </div>
                      <div className="mt-1.5 font-mono text-[9px] text-navy-400">
                        {progress.have}/{progress.need} frames to confirm
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>

        <section className="panel-dark">
          <div className="flex items-center justify-between gap-3 border-b border-white/10 px-5 py-3">
            <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-mint-200">
              Hands / customers
            </span>
            <span className="font-mono text-[10px] text-lavender-300">{hands.length}</span>
          </div>
          <div className="max-h-40 space-y-1.5 overflow-y-auto p-3">
            {hands.length === 0 && (
              <Empty text="No hands detected. Hand model is driving the touch signal." dark />
            )}
            {hands.map((h) => (
              <div
                key={h.hand_id}
                className="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 px-3 py-2"
              >
                <span className="font-mono text-[11px] text-lavender-100">
                  {h.customer_id}{" "}
                  <span className="text-lavender-300/70">
                    (hand {h.hand_id}, {h.hits} frames)
                  </span>
                </span>
                <span className="font-mono text-[10px] text-mint-200">
                  {(h.score * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">Interaction engine</span>
            <span className="meta">yolo {String(snap?.hud.infer_ms ?? 0)}ms</span>
          </div>
          <div className="max-h-56 space-y-1.5 overflow-y-auto p-3">
            {events.length === 0 && <Empty text="No events emitted in this session yet." />}
            {events.map((e) => (
              <div
                key={e.event_uid}
                className="flex items-center gap-2 rounded-xl border border-lavender-200 bg-lavender-100/70 px-3 py-2"
              >
                <span className="meta">{clock(e.ts)}</span>
                <EventBadge type={e.type} />
                <span className="truncate text-[11px] text-navy-700">{e.product_name}</span>
                <span className="meta ml-auto shrink-0">#{e.track_id}</span>
                {e.hand_id != null && (
                  <span className="meta shrink-0">hand {e.hand_id}</span>
                )}
              </div>
            ))}
          </div>
        </section>

        {error && (
          <div className="panel border-rose-200 p-4 font-mono text-[11px] text-rose-300">
            backend unreachable: {error}
          </div>
        )}
      </div>
    </div>
  );
}

function Empty({ text, dark }: { text: string; dark?: boolean }) {
  return (
    <div
      className={`px-2 py-6 text-center text-[11px] ${
        dark ? "text-lavender-300/80" : "text-navy-400"
      }`}
    >
      {text}
    </div>
  );
}
