"use client";

import { useMemo } from "react";
import type { LedgerEvent } from "@/lib/api";

export type DateRangePreset = "all" | "15m" | "1h" | "today";

interface LedgerFilterBarProps {
  search: string;
  onSearchChange: (val: string) => void;
  selectedType: string;
  onTypeChange: (val: string) => void;
  dateRange: DateRangePreset;
  onDateRangeChange: (preset: DateRangePreset) => void;
  events: LedgerEvent[];
  filteredCount: number;
  totalCount: number;
}

const EVENT_CHIPS = [
  { label: "All", value: "" },
  { label: "Picked Up", value: "PICKED_UP" },
  { label: "In Basket", value: "PLACED_IN_BASKET" },
  { label: "Put Back", value: "PUT_BACK" },
  { label: "Checked Out", value: "CHECKED_OUT" },
  { label: "Touch", value: "TOUCH" },
  { label: "Track Lost", value: "TRACK_LOST" },
];

export default function LedgerFilterBar({
  search,
  onSearchChange,
  selectedType,
  onTypeChange,
  dateRange,
  onDateRangeChange,
  events,
  filteredCount,
  totalCount,
}: LedgerFilterBarProps) {
  // Export filtered events as CSV
  const handleExportFiltered = () => {
    if (events.length === 0) return;
    const headers = [
      "event_uid",
      "timestamp",
      "type",
      "product_name",
      "product_id",
      "track_id",
      "session_id",
      "hand_id",
      "basket_track_id",
      "inferred",
      "resolved",
    ];

    const rows = events.map((e) => [
      e.event_uid,
      new Date(e.ts * 1000).toISOString(),
      e.type,
      `"${(e.product_name || "").replace(/"/g, '""')}"`,
      e.product_id || "",
      e.track_id ?? "",
      e.session_id || "",
      e.hand_id ?? "",
      e.basket_track_id ?? "",
      e.inferred ?? 0,
      e.resolution ? `"${e.resolution.replace(/"/g, '""')}"` : e.resolved ? "resolved" : "",
    ]);

    const csvContent =
      "data:text/csv;charset=utf-8," +
      [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute(
      "download",
      `surveil_ledger_filtered_${Date.now()}.csv`,
    );
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="space-y-3 rounded-2xl border border-lavender-200 bg-white/80 p-4 shadow-soft">
      {/* Search and Date presets */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-1 min-w-[240px] items-center gap-2">
          <div className="relative w-full max-w-sm">
            <input
              type="text"
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder="Search product, ID, session, track..."
              className="field w-full pl-8 pr-3"
            />
            <span className="pointer-events-none absolute left-3 top-2.5 text-navy-400">
              🔍
            </span>
          </div>

          {search && (
            <button
              type="button"
              onClick={() => onSearchChange("")}
              className="text-xs text-navy-400 hover:text-navy-700"
            >
              Clear
            </button>
          )}
        </div>

        {/* Date presets */}
        <div className="flex items-center gap-1.5 text-xs">
          <span className="text-[10px] uppercase font-semibold text-navy-400">Time:</span>
          {(["all", "15m", "1h", "today"] as DateRangePreset[]).map((preset) => (
            <button
              key={preset}
              type="button"
              onClick={() => onDateRangeChange(preset)}
              className={`rounded-lg px-2.5 py-1 text-[11px] font-medium transition ${
                dateRange === preset
                  ? "bg-navy-800 text-white shadow-sm"
                  : "bg-lavender-100 text-navy-600 hover:bg-lavender-200"
              }`}
            >
              {preset === "all"
                ? "All Time"
                : preset === "15m"
                  ? "Last 15m"
                  : preset === "1h"
                    ? "Last 1h"
                    : "Today"}
            </button>
          ))}
        </div>

        {/* Export filtered CSV */}
        <button
          type="button"
          onClick={handleExportFiltered}
          disabled={filteredCount === 0}
          className="btn !py-1.5 !px-3 !text-xs font-medium ml-auto"
        >
          Export Filtered CSV ({filteredCount})
        </button>
      </div>

      {/* Event type pills */}
      <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t border-lavender-100">
        <span className="text-[10px] uppercase font-semibold text-navy-400 mr-1">
          Type:
        </span>
        {EVENT_CHIPS.map((chip) => (
          <button
            key={chip.value}
            type="button"
            onClick={() => onTypeChange(chip.value)}
            className={`rounded-full px-3 py-1 text-[10px] font-medium transition ${
              selectedType === chip.value
                ? "bg-teal-600 text-white shadow-sm font-semibold"
                : "border border-lavender-200 bg-white text-navy-600 hover:bg-lavender-100"
            }`}
          >
            {chip.label}
          </button>
        ))}

        <span className="ml-auto font-mono text-[11px] text-navy-400">
          Showing <span className="font-semibold text-navy-700">{filteredCount}</span> of {totalCount}
        </span>
      </div>
    </div>
  );
}
