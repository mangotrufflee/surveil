"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, SNAPSHOT_URL, STREAM_URL, type LiveSnapshot, type PipelineStatus } from "@/lib/api";
import { usePolling } from "@/lib/usePolling";
import { StateBadge, EventBadge } from "@/components/Badges";
import { ago, clock } from "@/lib/format";
import ThresholdsPanel from "@/components/ThresholdsPanel";
import BasketRoiPicker from "@/components/BasketRoiPicker";
import HandBackendPicker from "@/components/HandBackendPicker";
import StateMachinePanel from "@/components/StateMachinePanel";
import ProductTrailOverlay from "@/components/ProductTrailOverlay";
import CameraGrid, { type GridMode } from "@/components/CameraGrid";

export default function LiveMonitor() {
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [streamNonce, setStreamNonce] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [source, setSource] = useState("0");
  const [showSettings, setShowSettings] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showTrails, setShowTrails] = useState(true);
  const [isSnapshotting, setIsSnapshotting] = useState(false);
  const [flashFrame, setFlashFrame] = useState(false);
  const [activeCamId, setActiveCamId] = useState("cam-1");
  const [gridMode, setGridMode] = useState<GridMode>("single");
  const [lastFrameTs, setLastFrameTs] = useState<number>(Date.now());

  const frameRef = useRef<HTMLDivElement>(null);
  const streamImgRef = useRef<HTMLImageElement>(null);

  // Poll live telemetry with latency measurement
  const fetchLive = useCallback(async () => {
    const t0 = performance.now();
    try {
      const res = await api.live();
      setLatencyMs(Math.round(performance.now() - t0));
      setLastFrameTs(Date.now());
      return res;
    } catch (e) {
      setLatencyMs(null);
      throw e;
    }
  }, []);

  const { data: snap, error, refresh } = usePolling<LiveSnapshot>(fetchLive, 400);
  const { data: status, refresh: refreshStatus } = usePolling<PipelineStatus>(
    () => api.status(),
    1500,
  );

  useEffect(() => {
    if (status?.camera_source) setSource(status.camera_source);
  }, [status?.camera_source]);

  // Fullscreen change listener
  useEffect(() => {
    const handleFsChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener("fullscreenchange", handleFsChange);
    return () => document.removeEventListener("fullscreenchange", handleFsChange);
  }, []);

  // Keyboard shortcut listener ('F' for fullscreen)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.target instanceof HTMLSelectElement
      ) {
        return;
      }
      if (e.key === "f" || e.key === "F") {
        e.preventDefault();
        toggleFullscreen();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const toggleFullscreen = useCallback(() => {
    if (!frameRef.current) return;
    if (!document.fullscreenElement) {
      frameRef.current.requestFullscreen().catch((err) => {
        console.warn("Fullscreen request failed:", err);
      });
    } else {
      document.exitFullscreen().catch((err) => {
        console.warn("Exit fullscreen failed:", err);
      });
    }
  }, []);

  // Freeze Frame / Snapshot Tool
  const takeSnapshot = useCallback(async () => {
    setIsSnapshotting(true);
    setFlashFrame(true);
    setTimeout(() => setFlashFrame(false), 300);

    try {
      // First try fetching full JPEG from backend endpoint
      const res = await fetch(`${SNAPSHOT_URL}?t=${Date.now()}`);
      if (!res.ok) throw new Error("Backend snapshot unavailable");
      const blob = await res.blob();

      // Trigger automatic file download
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const now = new Date();
      const pad = (n: number) => String(n).padStart(2, "0");
      const filename = `surveil-cctv-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(
        now.getDate(),
      )}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}.jpg`;
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch {
      // Fallback: capture via offscreen HTML5 canvas from img element
      if (streamImgRef.current && streamImgRef.current.complete) {
        const img = streamImgRef.current;
        const canvas = document.createElement("canvas");
        canvas.width = img.naturalWidth || 640;
        canvas.height = img.naturalWidth || 480;
        const ctx = canvas.getContext("2d");
        if (ctx) {
          ctx.drawImage(img, 0, 0);
          // Add watermark timestamp
          ctx.fillStyle = "rgba(0,0,0,0.6)";
          ctx.fillRect(10, canvas.height - 35, 380, 26);
          ctx.fillStyle = "#A5EBD1";
          ctx.font = "14px monospace";
          ctx.fillText(`SURVEIL CCTV [${new Date().toISOString()}]`, 20, canvas.height - 18);

          canvas.toBlob((b) => {
            if (!b) return;
            const url = URL.createObjectURL(b);
            const a = document.createElement("a");
            a.href = url;
            a.download = `surveil-snapshot-${Date.now()}.jpg`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
          }, "image/jpeg");
        }
      }
    } finally {
      setIsSnapshotting(false);
    }
  }, []);

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

  // Health and connection calculation
  const streamFps = status?.fps ?? 0;
  const isStalled = running && Date.now() - lastFrameTs > 3000;
  const connectionQuality: "STABLE" | "DEGRADED" | "OFFLINE" = !running
    ? "OFFLINE"
    : isStalled || (latencyMs !== null && latencyMs > 600)
      ? "DEGRADED"
      : "STABLE";

  // Zone conversion for basket picker
  const liveRoi = ((): [number, number, number, number] | null => {
    if (!snap?.basket_zone || !snap.frame_size) return null;
    const [fw, fh] = snap.frame_size;
    if (!fw || !fh) return null;
    const [x1, y1, x2, y2] = snap.basket_zone;
    return [x1 / fw, y1 / fh, (x2 - x1) / fw, (y2 - y1) / fh];
  })();

  // Primary video slot
  const primaryVideoFeed = (
    <div
      ref={frameRef}
      className={`relative flex flex-col justify-center overflow-hidden bg-navy-950 ${
        isFullscreen ? "h-screen w-screen p-0" : "w-full"
      }`}
    >
      {/* Visual shutter flash on snapshot */}
      {flashFrame && (
        <div className="pointer-events-none absolute inset-0 z-40 bg-white/40 transition-opacity duration-300" />
      )}

      {running ? (
        <div className="relative mx-auto flex h-full w-full items-center justify-center">
          {/* Live MJPEG Stream */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            ref={streamImgRef}
            key={streamNonce}
            src={STREAM_URL}
            crossOrigin="anonymous"
            alt="Annotated camera feed with product and hand detections"
            className="block max-h-[70vh] w-full object-contain"
          />

          {/* Rank 8: Product Trail Visualization Overlay */}
          <ProductTrailOverlay
            states={states}
            frameSize={snap?.frame_size ?? [640, 480]}
            enabled={showTrails}
          />

          {/* Fullscreen HUD & Controls */}
          {isFullscreen && (
            <div className="pointer-events-none absolute inset-0 z-30 flex flex-col justify-between p-6">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 rounded-full bg-navy-900/80 px-4 py-2 backdrop-blur-md">
                  <span className="h-2 w-2 rounded-full bg-teal-400 animate-pulse" />
                  <span className="font-mono text-xs font-bold text-white">
                    SURVEIL LIVE · CAM 01
                  </span>
                  <span className="font-mono text-[10px] text-mint-300">
                    {streamFps.toFixed(1)} FPS
                  </span>
                  {latencyMs !== null && (
                    <span className="font-mono text-[10px] text-lavender-300">
                      {latencyMs}ms ping
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={toggleFullscreen}
                  className="pointer-events-auto rounded-full bg-white/20 px-4 py-2 font-mono text-xs text-white backdrop-blur-md transition hover:bg-white/30"
                >
                  Exit Fullscreen (ESC)
                </button>
              </div>

              <div className="flex items-center justify-between">
                <div className="flex gap-2">
                  <span className="rounded-lg bg-navy-900/80 px-3 py-1.5 font-mono text-[11px] text-lavender-200 backdrop-blur-md">
                    {states.length} products tracked
                  </span>
                  <span className="rounded-lg bg-navy-900/80 px-3 py-1.5 font-mono text-[11px] text-lavender-200 backdrop-blur-md">
                    {hands.length} hands active
                  </span>
                </div>
                <div className="pointer-events-auto flex gap-2">
                  <button
                    type="button"
                    onClick={takeSnapshot}
                    className="rounded-full bg-teal-500/90 px-4 py-1.5 font-mono text-xs font-semibold text-white backdrop-blur-md transition hover:bg-teal-500"
                  >
                    Take Snapshot
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="flex aspect-video flex-col items-center justify-center gap-2 bg-gradient-to-br from-navy-900 to-[#121624] text-lavender-300">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white/5 text-lg font-mono text-mint-300">
            OFF
          </div>
          <div className="text-sm font-medium text-lavender-100">Camera is stopped</div>
          <div className="text-[11px] text-navy-400">
            Start the pipeline below to begin observing and tracking products.
          </div>
        </div>
      )}
    </div>
  );

  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_390px]">
      {/* ------------------------------------------------------ stream column */}
      <div className="space-y-5">
        <section className="panel overflow-hidden">
          <div className="panel-head flex-wrap">
            <div className="flex flex-wrap items-center gap-3">
              <span className="panel-title">Live CCTV Monitor</span>

              {/* Status Chip */}
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

              {/* Rank 3: Stream Health & Latency Indicator */}
              {running && (
                <div className="flex items-center gap-2 rounded-full border border-lavender-200 bg-white/80 px-2.5 py-0.5 font-mono text-[10px] text-navy-600 shadow-sm">
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      connectionQuality === "STABLE"
                        ? "bg-emerald-500"
                        : connectionQuality === "DEGRADED"
                          ? "bg-amber-500 animate-ping"
                          : "bg-rose-500"
                    }`}
                  />
                  <span>{streamFps.toFixed(0)} FPS</span>
                  <span className="text-navy-300">·</span>
                  <span>{latencyMs !== null ? `${latencyMs}ms` : "-"}</span>
                  <span className="text-navy-300">·</span>
                  <span
                    className={`font-semibold ${
                      connectionQuality === "STABLE"
                        ? "text-teal-600"
                        : connectionQuality === "DEGRADED"
                          ? "text-amber-600"
                          : "text-rose-500"
                    }`}
                  >
                    {connectionQuality}
                  </span>
                </div>
              )}

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
                  no hands detected
                </span>
              )}
            </div>

            {/* Toolbar Quick Action Buttons: Snapshot, Trails, Fullscreen */}
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setShowTrails((v) => !v)}
                className={`btn !py-1 !px-2.5 !text-[11px] ${
                  showTrails ? "bg-teal-100 text-teal-800 border-teal-300" : ""
                }`}
                title="Toggle product movement trails"
              >
                Trails {showTrails ? "ON" : "OFF"}
              </button>

              <button
                type="button"
                disabled={!running || isSnapshotting}
                onClick={takeSnapshot}
                className="btn !py-1 !px-2.5 !text-[11px]"
                title="Save HD frame snapshot with watermark"
              >
                {isSnapshotting ? "Saving..." : "Snapshot"}
              </button>

              <button
                type="button"
                onClick={toggleFullscreen}
                className="btn !py-1 !px-2.5 !text-[11px]"
                title="Toggle full screen mode (or press 'F')"
              >
                Fullscreen
              </button>
            </div>
          </div>

          {/* Rank 4: Multi-Camera Feed Grid Switcher */}
          <div className="p-4">
            <CameraGrid
              primarySlot={primaryVideoFeed}
              activeCamId={activeCamId}
              onSelectCam={setActiveCamId}
              gridMode={gridMode}
              onGridModeChange={setGridMode}
            />
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
            <ThresholdsPanel
              onSaved={() => {
                refresh();
                refreshStatus();
              }}
            />
            <div className="space-y-5">
              <BasketRoiPicker
                frameSize={snap?.frame_size ?? null}
                roi={liveRoi}
                detected={status?.basket_mode === "yolo"}
                disabled={!running}
                onSaved={() => {
                  refresh();
                  refreshStatus();
                }}
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

              const basketThresholdRatio = snap?.thresholds.basket_overlap_ratio ?? 0.5;
              const basketConfirmFrames = snap?.thresholds.basket_confirm_frames ?? 4;
              const basketThresholdMet = s.basket_overlap >= basketThresholdRatio;

              const progress =
                t === "LIFTING"
                  ? {
                      have: s.lift_frames,
                      need: snap?.thresholds.lift_confirm_frames ?? 5,
                      color: "bg-amber-500",
                      label: `${s.lift_frames}/${snap?.thresholds.lift_confirm_frames ?? 5} frames to lift`,
                    }
                  : t === "RETURNING"
                    ? {
                        have: s.return_frames,
                        need: snap?.thresholds.return_confirm_frames ?? 5,
                        color: "bg-blue-500",
                        label: `${s.return_frames}/${snap?.thresholds.return_confirm_frames ?? 5} frames to return`,
                      }
                    : (t === "IN_HAND" && (s.basket_frames > 0 || basketThresholdMet)) ||
                        t === "IN_BASKET"
                      ? {
                          have: t === "IN_BASKET" ? basketConfirmFrames : s.basket_frames,
                          need: basketConfirmFrames,
                          color: "bg-[#7C74C9]",
                          label:
                            t === "IN_BASKET"
                              ? `Confirmed PLACED_IN_BASKET (≥50% for ${basketConfirmFrames} frames)`
                              : `${s.basket_frames}/${basketConfirmFrames} frames (≥50% in basket) → PLACED_IN_BASKET`,
                        }
                      : null;

              return (
                <div
                  key={s.track_id}
                  className={`rounded-2xl border p-3 transition ${
                    t === "IN_BASKET"
                      ? "border-[#7C74C9]/40 bg-[#F5F3FD]"
                      : "border-lavender-200 bg-lavender-100/70"
                  }`}
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
                      <span
                        className={`chip ${
                          basketThresholdMet
                            ? "border-[#7C74C9] bg-[#EDEAF9] text-[#5F58AE] font-semibold ring-1 ring-[#7C74C9]/40"
                            : "border-[#E0DDF6] bg-[#F1EFFC] text-[#5F58AE]"
                        }`}
                        title="Condition: >= 50% of the box inside basket for 4 frames -> PLACED_IN_BASKET"
                      >
                        <span
                          className={`mr-1 inline-block h-1.5 w-1.5 rounded-full ${
                            basketThresholdMet ? "bg-[#7C74C9] animate-pulse" : "bg-[#7C74C9]/50"
                          }`}
                        />
                        basket {(s.basket_overlap * 100).toFixed(0)}%
                        {basketThresholdMet ? " (≥50% met)" : " (<50%)"}
                      </span>
                    )}
                    <span className="chip border-lavender-300 bg-white text-navy-500">
                      age {ago(s.age_s)}
                    </span>
                  </div>

                  {/* Confirmation Progress for PLACED_IN_BASKET / LIFTING / RETURNING */}
                  {progress && (
                    <div className="mt-2.5">
                      <div className="h-1.5 overflow-hidden rounded-full bg-lavender-200">
                        <div
                          className={`h-full rounded-full transition-all duration-300 ${
                            progress.color || "bg-teal-500"
                          }`}
                          style={{
                            width: `${Math.min(100, (progress.have / Math.max(1, progress.need)) * 100)}%`,
                          }}
                        />
                      </div>
                      <div className="mt-1.5 flex items-center justify-between font-mono text-[9px] text-navy-500">
                        <span>{progress.label}</span>
                        <span>
                          {progress.have}/{progress.need}
                        </span>
                      </div>
                    </div>
                  )}

                  {t === "IN_BASKET" && (
                    <div className="mt-2 flex items-center gap-1.5 rounded-lg border border-[#7C74C9]/30 bg-[#EDEAF9]/70 px-2 py-0.5 text-[9px] font-mono text-[#5F58AE]">
                      <span className="h-1.5 w-1.5 rounded-full bg-[#7C74C9]" />
                      <span>PLACED_IN_BASKET (≥ 50% overlap for 4 frames confirmed)</span>
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
