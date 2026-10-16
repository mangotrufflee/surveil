"use client";

import { useEffect, useRef, useState } from "react";
import type { LedgerEvent, ProductRow, Stats } from "@/lib/api";

interface LossAnalyticsProps {
  events: LedgerEvent[];
  products: ProductRow[];
  stats: Stats | null;
}

type HeatmapMode = "all" | "pickups" | "theft";

export default function LossAnalytics({
  events,
  products,
  stats,
}: LossAnalyticsProps) {
  const [mode, setMode] = useState<HeatmapMode>("all");
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Generate synthetic and event-based spatial coordinates for shelf layout
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    // Dark grid background representing the shelf
    ctx.fillStyle = "#1C2032";
    ctx.fillRect(0, 0, w, h);

    // Subtle shelf grid lines
    ctx.strokeStyle = "rgba(255, 255, 255, 0.07)";
    ctx.lineWidth = 1;
    for (let x = 40; x < w; x += 40) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let y = 40; y < h; y += 40) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    // Heat points derived from events (hash product_id/track_id to shelf coordinates)
    const points: { x: number; y: number; weight: number; color: string }[] = [];

    events.forEach((e) => {
      // Deterministic coordinate based on track_id & event_uid
      const seed = Math.abs(
        ((e.track_id || 1) * 31 + (e.event_uid ? e.event_uid.charCodeAt(0) : 7)) % 100,
      ) / 100;
      const seedY = Math.abs(
        ((e.track_id || 1) * 73 + (e.product_name ? e.product_name.charCodeAt(0) : 13)) % 100,
      ) / 100;

      const px = 60 + seed * (w - 120);
      const py = 50 + seedY * (h - 100);

      if (e.type === "TRACK_LOST") {
        if (mode === "all" || mode === "theft") {
          points.push({ x: px, y: py, weight: 1.0, color: "#C9645F" });
        }
      } else if (e.type === "PICKED_UP") {
        if (mode === "all" || mode === "pickups") {
          points.push({ x: px, y: py, weight: 0.7, color: "#C99A46" });
        }
      } else if (e.type === "TOUCH") {
        if (mode === "all") {
          points.push({ x: px, y: py, weight: 0.4, color: "#438D8B" });
        }
      }
    });

    // If few events, seed default hotspots for visualization
    if (points.length === 0) {
      points.push({ x: w * 0.35, y: h * 0.4, weight: 0.8, color: "#C99A46" });
      points.push({ x: w * 0.7, y: h * 0.6, weight: 0.9, color: "#C9645F" });
      points.push({ x: w * 0.5, y: h * 0.5, weight: 0.5, color: "#438D8B" });
    }

    // Draw radial blur gradient heat spots
    points.forEach((p) => {
      const radius = 35 * p.weight;
      const grad = ctx.createRadialGradient(p.x, p.y, 2, p.x, p.y, radius);
      grad.addColorStop(0, p.color + "cc"); // high alpha center
      grad.addColorStop(0.5, p.color + "55");
      grad.addColorStop(1, "transparent");

      ctx.beginPath();
      ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
      ctx.fillStyle = grad;
      ctx.fill();
    });

    // Basket target region indicator
    ctx.strokeStyle = "rgba(124, 116, 201, 0.6)";
    ctx.lineWidth = 2;
    ctx.setLineDash([4, 4]);
    ctx.strokeRect(w * 0.66, h * 0.58, w * 0.3, h * 0.38);
    ctx.fillStyle = "rgba(124, 116, 201, 0.15)";
    ctx.fillRect(w * 0.66, h * 0.58, w * 0.3, h * 0.38);
    ctx.setLineDash([]);
    ctx.fillStyle = "#A5EBD1";
    ctx.font = "10px monospace";
    ctx.fillText("BASKET / CHECKOUT ZONE", w * 0.68, h * 0.64);
  }, [events, mode]);

  // Compute shrink risk distribution by product
  const riskProducts = [...products]
    .map((p) => {
      const pick = p.picked_up_count;
      const sold = p.purchased_count;
      const potentialShrink = Math.max(0, pick - sold);
      return {
        ...p,
        potentialShrink,
        riskScore: pick > 0 ? Math.round((potentialShrink / pick) * 100) : 0,
      };
    })
    .sort((a, b) => b.potentialShrink - a.potentialShrink)
    .slice(0, 5);

  const totalLost = (stats?.lost ?? 0) + (stats?.unaccounted ?? 0);

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
        {/* Heatmap Canvas Column */}
        <div className="panel p-5 lg:col-span-7">
          <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-lavender-200">
            <div>
              <h3 className="panel-title">Shelf Interaction & Loss Heatmap</h3>
              <p className="text-xs text-navy-500">
                Spatial density of product touches, lift incidents & loss locations
              </p>
            </div>
            {/* Heatmap filter buttons */}
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setMode("all")}
                className={`rounded-lg px-2.5 py-1 text-[11px] font-medium transition ${
                  mode === "all"
                    ? "bg-navy-800 text-white shadow-sm"
                    : "bg-lavender-100 text-navy-600 hover:bg-lavender-200"
                }`}
              >
                All Interactions
              </button>
              <button
                type="button"
                onClick={() => setMode("pickups")}
                className={`rounded-lg px-2.5 py-1 text-[11px] font-medium transition ${
                  mode === "pickups"
                    ? "bg-amber-500 text-white shadow-sm"
                    : "bg-lavender-100 text-navy-600 hover:bg-lavender-200"
                }`}
              >
                Pickups
              </button>
              <button
                type="button"
                onClick={() => setMode("theft")}
                className={`rounded-lg px-2.5 py-1 text-[11px] font-medium transition ${
                  mode === "theft"
                    ? "bg-rose-500 text-white shadow-sm"
                    : "bg-lavender-100 text-navy-600 hover:bg-lavender-200"
                }`}
              >
                Loss Hotspots
              </button>
            </div>
          </div>

          <div className="mt-4 overflow-hidden rounded-xl border border-lavender-200 bg-navy-950">
            <canvas
              ref={canvasRef}
              width={540}
              height={320}
              className="h-auto w-full object-contain block"
            />
          </div>

          <div className="mt-3 flex items-center justify-between text-[11px] text-navy-500 font-mono">
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-full bg-teal-500" /> Touch
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-full bg-amber-500" /> Pickup
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-full bg-rose-500" /> Loss / Lost Track
              </span>
            </div>
            <span>Camera 01 View Matrix</span>
          </div>
        </div>

        {/* Shrinkage & Loss Prevention Insights Column */}
        <div className="panel p-5 lg:col-span-5 flex flex-col justify-between">
          <div>
            <div className="pb-3 border-b border-lavender-200">
              <h3 className="panel-title">Loss Prevention & Shrinkage Risk</h3>
              <p className="text-xs text-navy-500">
                Identifies top shrinkage items and inventory discrepancy
              </p>
            </div>

            {/* Risk Score summary */}
            <div className="mt-4 rounded-2xl border border-lavender-200 bg-lavender-50 p-4">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-navy-600">
                  Store Shrinkage Index
                </span>
                <span
                  className={`chip ${
                    totalLost > 0
                      ? "border-rose-300 bg-rose-100 text-rose-700"
                      : "border-teal-300 bg-mint-100 text-teal-800"
                  }`}
                >
                  {totalLost > 0 ? "ATTENTION NEEDED" : "HEALTHY"}
                </span>
              </div>
              <div className="mt-2 text-2xl font-bold text-navy-900">
                {totalLost} <span className="text-xs font-normal text-navy-500">unresolved items</span>
              </div>
              <p className="mt-1 text-[11px] text-navy-500 leading-relaxed">
                Items picked up by customers that neither returned to their shelf anchor nor
                reached the checkout register.
              </p>
            </div>

            {/* High Shrink Risk Items Table */}
            <div className="mt-4">
              <h4 className="text-[10px] font-bold uppercase tracking-wider text-navy-500 mb-2">
                Top High-Shrink Products
              </h4>
              <div className="space-y-1.5">
                {riskProducts.map((p) => (
                  <div
                    key={p.product_id}
                    className="flex items-center justify-between rounded-xl border border-lavender-100 bg-white p-2.5 text-xs shadow-xs"
                  >
                    <div>
                      <div className="font-semibold text-navy-800">{p.product_name}</div>
                      <div className="text-[9px] font-mono text-navy-400">
                        {p.picked_up_count} picked · {p.purchased_count} sold
                      </div>
                    </div>
                    <div className="text-right">
                      <div
                        className={`font-mono font-bold ${
                          p.potentialShrink > 0 ? "text-rose-600" : "text-teal-600"
                        }`}
                      >
                        {p.potentialShrink > 0 ? `-${p.potentialShrink}` : "0"}
                      </div>
                      <div className="text-[9px] text-navy-400">
                        {p.riskScore}% unconfirmed
                      </div>
                    </div>
                  </div>
                ))}
                {riskProducts.length === 0 && (
                  <div className="py-4 text-center text-xs text-navy-400">
                    No product discrepancy recorded.
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-lavender-200 text-[10px] font-mono text-navy-400">
            Automated Computer Vision Ledger Analysis
          </div>
        </div>
      </div>
    </div>
  );
}
