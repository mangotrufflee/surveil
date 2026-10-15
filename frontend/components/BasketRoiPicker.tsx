"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type BBox } from "@/lib/api";

type Roi = [number, number, number, number]; // normalised x, y, w, h

const MIN_FRACTION = 0.02;

/**
 * Drag the basket zone directly onto the live feed.
 *
 * The wrapper is locked to the frame's aspect ratio, so it exactly contains the
 * image with no letterboxing and a click maps to frame pixels by a plain
 * multiply. (With `object-contain` in a mismatched box you would have to
 * subtract the letterbox offset, which is where these tools usually go wrong.)
 */
export default function BasketRoiPicker({
  frameSize,
  roi,
  detected,
  disabled,
  onSaved,
}: {
  frameSize: [number, number] | null;
  roi: Roi | null;
  detected: boolean;
  disabled?: boolean;
  onSaved?: () => void;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState<Roi | null>(null);
  const [start, setStart] = useState<{ x: number; y: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const aspect = frameSize ? frameSize[0] / frameSize[1] : 4 / 3;

  const toFraction = useCallback((clientX: number, clientY: number) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) return null;
    const x = (clientX - rect.left) / rect.width;
    const y = (clientY - rect.top) / rect.height;
    return {
      x: Math.min(1, Math.max(0, x)),
      y: Math.min(1, Math.max(0, y)),
    };
  }, []);

  const onPointerDown = (e: React.PointerEvent) => {
    if (disabled) return;
    const p = toFraction(e.clientX, e.clientY);
    if (!p) return;
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    setStart(p);
    setDraft([p.x, p.y, 0, 0]);
    setMsg(null);
    setErr(null);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!start) return;
    const p = toFraction(e.clientX, e.clientY);
    if (!p) return;
    const x = Math.min(start.x, p.x);
    const y = Math.min(start.y, p.y);
    setDraft([x, y, Math.abs(p.x - start.x), Math.abs(p.y - start.y)]);
  };

  const finish = useCallback(async () => {
    if (!draft) return;
    setStart(null);
    const [x, y, w, h] = draft;
    if (w < MIN_FRACTION || h < MIN_FRACTION) {
      setErr("That region is too small - drag a larger box.");
      setDraft(null);
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await api.setBasketRoi([x, y, w, h]);
      setMsg("Basket zone saved.");
      setDraft(null);
      onSaved?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [draft, onSaved]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setDraft(null);
        setStart(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const shown = draft ?? roi;
  const frameBBox = useCallback((): BBox | null => {
    if (!shown || !frameSize) return null;
    const [fw, fh] = frameSize;
    return {
      x1: Math.round(shown[0] * fw),
      y1: Math.round(shown[1] * fh),
      x2: Math.round((shown[0] + shown[2]) * fw),
      y2: Math.round((shown[1] + shown[3]) * fh),
    };
  }, [shown, frameSize]);

  const box = frameBBox();

  return (
    <section className="panel">
      <div className="panel-head">
        <span className="panel-title">Basket zone</span>
        <span className="meta">
          {detected ? "detected by model" : roi ? "drawn region" : "not set"}
        </span>
      </div>

      <div className="space-y-3 p-4">
        <p className="text-[10px] leading-relaxed text-navy-500">
          {detected
            ? "The model has a basket class, so the zone is detected automatically. Drawing one still overrides it."
            : "Stock COCO cannot detect a basket, so drag the region the basket actually occupies in the camera view."}
        </p>

        <div
          ref={wrapRef}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={finish}
          onPointerCancel={() => {
            setStart(null);
            setDraft(null);
          }}
          style={{ aspectRatio: String(aspect) }}
          className={`relative w-full touch-none select-none overflow-hidden rounded-2xl border-2 border-dashed ${
            disabled
              ? "cursor-not-allowed border-lavender-300 bg-lavender-100 opacity-60"
              : start
                ? "cursor-crosshair border-teal-400 bg-mint-100"
                : "cursor-crosshair border-lavender-300 bg-lavender-100 hover:border-teal-300"
          }`}
          title={disabled ? "Start the pipeline first" : "Drag to draw the basket zone"}
        >
          {shown && (
            <div
              className="pointer-events-none absolute rounded-xl border-2 border-teal-500 bg-mint-200/30"
              style={{
                left: `${shown[0] * 100}%`,
                top: `${shown[1] * 100}%`,
                width: `${shown[2] * 100}%`,
                height: `${shown[3] * 100}%`,
              }}
            >
              <span className="absolute -top-0.5 left-2 whitespace-nowrap rounded-full bg-teal-500 px-2 py-px font-mono text-[9px] font-bold text-white">
                BASKET
              </span>
            </div>
          )}
          {!shown && (
            <div className="absolute inset-0 flex items-center justify-center px-4 text-center text-[11px] text-navy-400">
              {disabled ? "Start the pipeline to set a zone" : "Drag here to draw the basket zone"}
            </div>
          )}
        </div>

        {box && (
          <div className="meta">
            px {box.x1},{box.y1} -&gt; {box.x2},{box.y2}
            {frameSize ? ` of ${frameSize[0]}x${frameSize[1]}` : ""}
          </div>
        )}

        <div className="flex gap-1.5">
          <button
            className="btn"
            disabled={busy || disabled}
            onClick={async () => {
              setBusy(true);
              setErr(null);
              try {
                await api.setBasketRoi(null);
                setMsg("Zone cleared - basket drops will not be detected.");
                setDraft(null);
                onSaved?.();
              } catch (e) {
                setErr(e instanceof Error ? e.message : String(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            Clear
          </button>
          <button
            className="btn"
            disabled={busy || disabled}
            onClick={async () => {
              setBusy(true);
              setErr(null);
              try {
                await api.setBasketRoi([0.66, 0.58, 0.32, 0.4]);
                setMsg("Default zone restored.");
                onSaved?.();
              } catch (e) {
                setErr(e instanceof Error ? e.message : String(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            Reset to default
          </button>
        </div>

        {msg && <div className="font-mono text-[10px] text-teal-600">{msg}</div>}
        {err && <div className="font-mono text-[10px] text-rose-300">{err}</div>}
      </div>
    </section>
  );
}
