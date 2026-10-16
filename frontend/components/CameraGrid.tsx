"use client";

import { useEffect, useState } from "react";

export type GridMode = "single" | "split" | "quad";

export interface CameraDef {
  id: string;
  name: string;
  location: string;
  status: "live" | "standby" | "recording";
  fps?: number;
}

export const CAMERAS: CameraDef[] = [
  { id: "cam-1", name: "CAM 01", location: "Shelf A (Overhead Live)", status: "live", fps: 30 },
  { id: "cam-2", name: "CAM 02", location: "Checkout Register A", status: "standby" },
  { id: "cam-3", name: "CAM 03", location: "Aisle 2 — Dry Goods", status: "standby" },
  { id: "cam-4", name: "CAM 04", location: "Store Entrance & Exit", status: "standby" },
];

interface CameraGridProps {
  primarySlot: React.ReactNode;
  activeCamId: string;
  onSelectCam: (id: string) => void;
  gridMode: GridMode;
  onGridModeChange: (mode: GridMode) => void;
}

export default function CameraGrid({
  primarySlot,
  activeCamId,
  onSelectCam,
  gridMode,
  onGridModeChange,
}: CameraGridProps) {
  const [clockStr, setClockStr] = useState("");

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setClockStr(
        now.toISOString().replace("T", " ").substring(0, 19) +
          "." +
          String(now.getMilliseconds()).padStart(3, "0"),
      );
    };
    updateTime();
    const interval = setInterval(updateTime, 100);
    return () => clearInterval(interval);
  }, []);

  const renderSimulatedFeed = (cam: CameraDef) => {
    return (
      <div
        key={cam.id}
        onClick={() => onSelectCam(cam.id)}
        className="group relative flex aspect-video cursor-pointer flex-col justify-between overflow-hidden rounded-xl border border-white/10 bg-gradient-to-b from-navy-950 via-[#121624] to-navy-950 p-3 shadow-inner transition hover:border-teal-400/50"
      >
        {/* CRT Scanline effect */}
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(18,22,36,0)_50%,rgba(0,0,0,0.35)_50%)] bg-[length:100%_4px] opacity-40" />

        {/* Header telemetry */}
        <div className="z-10 flex items-center justify-between text-[10px] font-mono tracking-wider">
          <div className="flex items-center gap-1.5 text-lavender-200">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />
            <span className="font-bold">{cam.name}</span>
            <span className="text-navy-400">· {cam.location}</span>
          </div>
          <span className="rounded bg-white/10 px-1.5 py-0.5 text-[9px] text-lavender-300">
            STANDBY
          </span>
        </div>

        {/* Center reticle */}
        <div className="z-10 flex flex-col items-center justify-center gap-1.5 text-center text-navy-400 group-hover:text-lavender-200 transition">
          <div className="flex h-10 w-10 items-center justify-center rounded-full border border-white/10 bg-white/5 text-xs font-mono">
            {cam.name.replace("CAM ", "C")}
          </div>
          <div className="text-[11px] font-medium text-lavender-300/80">{cam.location}</div>
          <div className="text-[9px] font-mono text-navy-500">RTSP Stream Ready · Click to Focus</div>
        </div>

        {/* Footer timestamp & REC */}
        <div className="z-10 flex items-center justify-between text-[9px] font-mono text-navy-400">
          <span>{clockStr}</span>
          <div className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-rose-500/80" />
            <span className="text-rose-400/90">REC [LOOP]</span>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-3">
      {/* Viewport layout selector */}
      <div className="flex items-center justify-between gap-2 px-1">
        <div className="flex items-center gap-1.5 text-xs font-medium text-navy-700">
          <span className="text-[10px] uppercase tracking-wider text-navy-400">Layout:</span>
          <button
            type="button"
            className={`rounded-lg px-2.5 py-1 text-[11px] font-medium transition ${
              gridMode === "single"
                ? "bg-navy-800 text-white shadow-sm"
                : "bg-white text-navy-600 hover:bg-lavender-100"
            }`}
            onClick={() => onGridModeChange("single")}
          >
            Focus (1x1)
          </button>
          <button
            type="button"
            className={`rounded-lg px-2.5 py-1 text-[11px] font-medium transition ${
              gridMode === "split"
                ? "bg-navy-800 text-white shadow-sm"
                : "bg-white text-navy-600 hover:bg-lavender-100"
            }`}
            onClick={() => onGridModeChange("split")}
          >
            Split (1+3)
          </button>
          <button
            type="button"
            className={`rounded-lg px-2.5 py-1 text-[11px] font-medium transition ${
              gridMode === "quad"
                ? "bg-navy-800 text-white shadow-sm"
                : "bg-white text-navy-600 hover:bg-lavender-100"
            }`}
            onClick={() => onGridModeChange("quad")}
          >
            Quad Grid (2x2)
          </button>
        </div>

        {/* Quick camera switch pills */}
        <div className="flex items-center gap-1 overflow-x-auto">
          {CAMERAS.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => onSelectCam(c.id)}
              className={`flex items-center gap-1 rounded-full px-2.5 py-1 text-[10px] font-mono transition ${
                activeCamId === c.id
                  ? "bg-teal-500 text-white font-semibold shadow-sm"
                  : "bg-white text-navy-600 hover:bg-lavender-100 border border-lavender-200"
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  c.status === "live"
                    ? "bg-emerald-400 animate-pulse"
                    : "bg-navy-400"
                }`}
              />
              {c.name}
            </button>
          ))}
        </div>
      </div>

      {/* Grid container based on selected layout */}
      {gridMode === "single" && (
        <div className="overflow-hidden rounded-2xl border border-lavender-200 bg-navy-950">
          {activeCamId === "cam-1"
            ? primarySlot
            : renderSimulatedFeed(CAMERAS.find((c) => c.id === activeCamId) ?? CAMERAS[0])}
        </div>
      )}

      {gridMode === "split" && (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
          <div className="overflow-hidden rounded-2xl border border-lavender-200 bg-navy-950 lg:col-span-2">
            {activeCamId === "cam-1"
              ? primarySlot
              : renderSimulatedFeed(CAMERAS.find((c) => c.id === activeCamId) ?? CAMERAS[0])}
          </div>
          <div className="flex flex-col gap-3">
            {CAMERAS.filter((c) => c.id !== activeCamId).map((c) =>
              c.id === "cam-1" ? (
                <div
                  key={c.id}
                  onClick={() => onSelectCam(c.id)}
                  className="cursor-pointer overflow-hidden rounded-xl border border-teal-400/40 hover:border-teal-400"
                >
                  {primarySlot}
                </div>
              ) : (
                renderSimulatedFeed(c)
              ),
            )}
          </div>
        </div>
      )}

      {gridMode === "quad" && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {CAMERAS.map((c) =>
            c.id === "cam-1" ? (
              <div
                key={c.id}
                onClick={() => onSelectCam(c.id)}
                className={`overflow-hidden rounded-xl border ${
                  activeCamId === c.id ? "border-teal-400 shadow-md" : "border-white/10"
                } bg-navy-950 cursor-pointer`}
              >
                {primarySlot}
              </div>
            ) : (
              renderSimulatedFeed(c)
            ),
          )}
        </div>
      )}
    </div>
  );
}
