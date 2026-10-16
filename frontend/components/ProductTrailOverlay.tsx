"use client";

import { useEffect, useRef } from "react";
import type { TrackState } from "@/lib/api";

interface Point {
  x: number;
  y: number;
  state: string;
  ts: number;
}

interface ProductTrailOverlayProps {
  states: TrackState[];
  frameSize: [number, number] | null;
  enabled: boolean;
}

const STATE_COLORS: Record<string, string> = {
  ON_SHELF: "#438D8B", // teal
  LIFTING: "#C99A46", // amber
  IN_HAND: "#C97A54", // warm orange
  RETURNING: "#5F84C4", // blue
  IN_BASKET: "#7C74C9", // purple
  LOST: "#C9645F", // rose
};

export default function ProductTrailOverlay({
  states,
  frameSize,
  enabled,
}: ProductTrailOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // Map of product_id -> history of centroids
  const trailsRef = useRef<Map<string, Point[]>>(new Map());

  useEffect(() => {
    if (!enabled) {
      trailsRef.current.clear();
      const canvas = canvasRef.current;
      if (canvas) {
        const ctx = canvas.getContext("2d");
        ctx?.clearRect(0, 0, canvas.width, canvas.height);
      }
      return;
    }

    const now = Date.now();
    const activeProductIds = new Set<string>();

    states.forEach((s) => {
      if (!s.box) return;
      const [x1, y1, x2, y2] = s.box;
      const cx = (x1 + x2) / 2;
      const cy = (y1 + y2) / 2;
      const pid = s.product_id || String(s.track_id);
      activeProductIds.add(pid);

      let history = trailsRef.current.get(pid);
      if (!history) {
        history = [];
        trailsRef.current.set(pid, history);
      }

      // Avoid adding points if product didn't move
      const last = history[history.length - 1];
      const dist = last ? Math.hypot(cx - last.x, cy - last.y) : 999;
      if (dist > 3 || history.length === 0) {
        history.push({ x: cx, y: cy, state: s.state, ts: now });
      }

      // Keep maximum 30 points and within last 4 seconds
      const maxAge = 4000;
      const pruned = history.filter((p) => now - p.ts < maxAge).slice(-30);
      trailsRef.current.set(pid, pruned);
    });

    // Clean up dead products after 5 seconds of inactivity
    for (const [pid, history] of trailsRef.current.entries()) {
      if (!activeProductIds.has(pid)) {
        const last = history[history.length - 1];
        if (!last || now - last.ts > 4500) {
          trailsRef.current.delete(pid);
        }
      }
    }

    // Render trails on canvas
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const [fw, fh] = frameSize ?? [640, 480];
    const scaleX = canvas.width / (fw || 640);
    const scaleY = canvas.height / (fh || 480);

    trailsRef.current.forEach((pts) => {
      if (pts.length < 2) return;

      for (let i = 1; i < pts.length; i++) {
        const p1 = pts[i - 1];
        const p2 = pts[i];
        const age = (now - p2.ts) / 4000;
        const alpha = Math.max(0.1, 1 - age);
        const color = STATE_COLORS[p2.state] || "#438D8B";

        ctx.beginPath();
        ctx.moveTo(p1.x * scaleX, p1.y * scaleY);
        ctx.lineTo(p2.x * scaleX, p2.y * scaleY);
        ctx.strokeStyle = color;
        ctx.globalAlpha = alpha * 0.85;
        ctx.lineWidth = Math.max(1.5, (i / pts.length) * 4);
        ctx.lineCap = "round";
        ctx.stroke();
      }

      // Draw glowing head dot
      const latest = pts[pts.length - 1];
      const headColor = STATE_COLORS[latest.state] || "#438D8B";
      ctx.beginPath();
      ctx.arc(latest.x * scaleX, latest.y * scaleY, 4, 0, Math.PI * 2);
      ctx.fillStyle = headColor;
      ctx.globalAlpha = 1;
      ctx.shadowColor = headColor;
      ctx.shadowBlur = 8;
      ctx.fill();
      ctx.shadowBlur = 0;
    });

    ctx.globalAlpha = 1;
  }, [states, frameSize, enabled]);

  if (!enabled) return null;

  const [fw, fh] = frameSize ?? [640, 480];

  return (
    <canvas
      ref={canvasRef}
      width={fw}
      height={fh}
      className="pointer-events-none absolute inset-0 h-full w-full object-contain"
    />
  );
}
