"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, STREAM_URL, type LiveSnapshot, type PipelineStatus } from "@/lib/api";
import { usePolling } from "@/lib/usePolling";
import { StateBadge, EventBadge } from "@/components/Badges";
import { ago, clock } from "@/lib/format";
import ThresholdsPanel from "@/components/ThresholdsPanel";
import BasketRoiPanel from "@/components/BasketRoiPanel";
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

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      {/* ------------------------------------------------------ stream column */}
      <div className="space-y-4">
        <section className="panel overflow-hidden">
          <div className="panel-head">
            <div className="flex items-center gap-3">
              <span className="panel-title">Live CCTV Monitor</span>
              <span
                className={`chip ${
                  running
                    ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                    : "border-rose-500/40 bg-rose-500/10 text-rose-300"
                }`}
              >
                <span
                  className={`mr-1 inline-block h-1.5 w-1.5 rounded-full ${
                    running ? "animate-pulse bg-emerald-400" : "bg-rose-400"
                  }`}
                />
                {running ? "STREAMING" : "STOPPED"}
              </span>
              {snap && snap.ignored_count > 0 && (
                <span
                  className="chip border-ink-600 bg-ink-800 text-slate-400"
                  title="The person class is counted but never boxed, highlighted or tracked."
                >
                  {snap.ignored_count} {snap.ignored_classes.join("/")} in frame - not tracked
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-[10px] text-slate-500">
                {status?.session_id ?? "no session"}
              </span>
            </div>
          </div>

          <div ref={frameRef} className="relative bg-black">
            {running ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                key={streamNonce}
                src={STREAM_URL}
                alt="Annotated camera feed with product and hand detections"
                className="block max-h-[68vh] w-full object-contain"
              />
            ) : (
              <div className="flex aspect-video flex-col items-center justify-center gap-2 text-slate-500">
                <div className="text-sm">Camera is stopped</div>
                <div className="text-[11px]">Start the pipeline to begin observing.</div>
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-end gap-2 border-t border-ink-700 p-3">
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
            <div className="border-t border-rose-500/30 bg-rose-500/10 px-3 py-2 font-mono text-[11px] text-rose-300">
              {actionError}
            </div>
          )}
        </section>

        {showSettings && (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <ThresholdsPanel onSaved={() => { refresh(); refreshStatus(); }} />
            <div className="space-y-4">
              <BasketRoiPanel
                roi={((status?.basket_mode ?? "none") as string) !== "none" ? snap?.basket_source ?? null : null}
                onSaved={() => { refresh(); refreshStatus(); }}
              />
              <StateMachinePanel />
            </div>
          </div>
        )}
      </div>

      {/* -------------------------------------------------------- side column */}
      <div className="space-y-4">
        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">Product states</span>
            <span className="font-mono text-[10px] text-slate-500">{states.length} tracked</span>
          </div>
          <div className="max-h-[38vh] overflow-y-auto p-2">
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
                  className="mb-1.5 rounded-lg border border-ink-700 bg-ink-850/60 p-2.5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="truncate text-xs font-medium text-slate-200">
                        {s.product_name}
                      </span>
                      <span className="font-mono text-[10px] text-slate-500">
                        #{s.track_id}
                      </span>
                    </div>
                    <StateBadge state={t} pulse={busy} />
                  </div>

                  <div className="mt-1.5 flex flex-wrap gap-1.5 text-[9px] uppercase tracking-wider">
                    {!s.anchor_confirmed && (
                      <span className="chip border-ink-600 bg-ink-800 text-slate-400">
                        settling {s.settle_frames}/{snap?.thresholds.settle_frames ?? 15}
                      </span>
                    )}
                    {s.touching && (
                      <span className="chip border-state-hand/40 bg-state-hand/10 text-state-hand">
                        hand {s.hand_id ?? "-"}
                      </span>
                    )}
                    <span
                      className={`chip ${
                        s.displaced
                          ? "border-state-lifting/40 bg-state-lifting/10 text-state-lifting"
                          : "border-ink-600 bg-ink-800 text-slate-500"
                      }`}
                    >
                      {s.displacement_px.toFixed(0)}px / {snap?.thresholds.shelf_displacement_px ?? 60}px
                    </span>
                    {s.basket_overlap > 0 && (
                      <span className="chip border-state-basket/40 bg-state-basket/10 text-state-basket">
                        basket {(s.basket_overlap * 100).toFixed(0)}%
                      </span>
                    )}
                    <span className="chip border-ink-600 bg-ink-800 text-slate-500">
                      age {ago(s.age_s)}
                    </span>
                  </div>

                  {progress && (
                    <div className="mt-2">
                      <div className="h-1 overflow-hidden rounded bg-ink-700">
                        <div
                          className="h-full bg-emerald-400 transition-all"
                          style={{
                            width: `${Math.min(100, (progress.have / Math.max(1, progress.need)) * 100)}%`,
                          }}
                        />
                      </div>
                      <div className="mt-1 font-mono text-[9px] text-slate-500">
                        {progress.have}/{progress.need} frames to confirm
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">Hands / customers</span>
            <span className="font-mono text-[10px] text-slate-500">{hands.length}</span>
          </div>
          <div className="max-h-40 overflow-y-auto p-2">
            {hands.length === 0 && (
              <Empty text="No hands detected. Hand model is driving the touch signal." />
            )}
            {hands.map((h) => (
              <div
                key={h.hand_id}
                className="mb-1 flex items-center justify-between rounded-md border border-ink-700 bg-ink-850/60 px-2.5 py-1.5"
              >
                <span className="font-mono text-[11px] text-slate-300">
                  {h.customer_id}{" "}
                  <span className="text-slate-600">
                    (hand {h.hand_id}, {h.hits} frames)
                  </span>
                </span>
                <span className="font-mono text-[10px] text-slate-500">
                  {(h.score * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">Interaction engine</span>
            <span className="font-mono text-[10px] text-slate-500">
              yolo {String(snap?.hud.infer_ms ?? 0)}ms
            </span>
          </div>
          <div className="max-h-56 space-y-1 overflow-y-auto p-2">
            {events.length === 0 && <Empty text="No events emitted in this session yet." />}
            {events.map((e) => (
              <div
                key={e.event_uid}
                className="flex items-center gap-2 rounded-md border border-ink-700 bg-ink-850/60 px-2.5 py-1.5"
              >
                <span className="font-mono text-[10px] text-slate-500">{clock(e.ts)}</span>
                <EventBadge type={e.type} />
                <span className="truncate text-[11px] text-slate-300">{e.product_name}</span>
                <span className="font-mono text-[10px] text-slate-600">#{e.track_id}</span>
                {e.hand_id != null && (
                  <span className="font-mono text-[10px] text-slate-600">hand {e.hand_id}</span>
                )}
              </div>
            ))}
          </div>
        </section>

        {error && (
          <div className="panel border-rose-500/40 p-3 font-mono text-[11px] text-rose-300">
            backend unreachable: {error}
          </div>
        )}
      </div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="px-2 py-4 text-center text-[11px] text-slate-600">{text}</div>;
}
