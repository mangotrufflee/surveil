"use client";

import { useCallback, useMemo, useState } from "react";
import {
  api,
  type Alert,
  type LedgerEvent,
  type PendingResponse,
  type PendingRow,
  type ProductRow,
  type SessionRow,
  type Stats,
} from "@/lib/api";
import { usePolling } from "@/lib/usePolling";
import { EventBadge } from "@/components/Badges";
import { ago, clock, stamp } from "@/lib/format";
import FunnelView from "@/components/FunnelView";
import LedgerFilterBar, { type DateRangePreset } from "@/components/LedgerFilterBar";
import IncidentDrawer, { type IncidentTarget } from "@/components/IncidentDrawer";
import LossAnalytics from "@/components/LossAnalytics";

export default function OwnerDashboard() {
  const [filterType, setFilterType] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [dateRange, setDateRange] = useState<DateRangePreset>("all");
  const [selectedIncident, setSelectedIncident] = useState<IncidentTarget | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: stats } = usePolling<Stats>(() => api.stats(), 2000);
  const { data: pending, refresh: refreshPending } = usePolling<PendingResponse>(
    () => api.pending(),
    2000,
  );
  const { data: purchases, refresh: refreshPurchases } = usePolling(() => api.purchases(), 4000);
  const { data: alerts, refresh: refreshAlerts } = usePolling(() => api.alerts(), 3000);
  const { data: products } = usePolling(() => api.products(), 5000);
  const { data: sessions } = usePolling(() => api.sessions(), 8000);
  const { data: events, refresh: refreshEvents } = usePolling(
    () => api.events({ limit: 200, type: filterType || undefined }),
    3000,
    [filterType],
  );

  const act = useCallback(
    async (label: string, fn: () => Promise<unknown>) => {
      setError(null);
      setNote(null);
      try {
        await fn();
        setNote(label);
        refreshEvents();
        refreshPending();
        refreshAlerts();
        refreshPurchases();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [refreshEvents, refreshPending, refreshAlerts, refreshPurchases],
  );

  // Filter events client-side by search query and date range
  const filteredEvents = useMemo(() => {
    const list = events?.events ?? [];
    const nowSec = Date.now() / 1000;

    return list.filter((e) => {
      // Date filter
      if (dateRange === "15m" && e.ts < nowSec - 900) return false;
      if (dateRange === "1h" && e.ts < nowSec - 3600) return false;
      if (dateRange === "today") {
        const midnight = new Date();
        midnight.setHours(0, 0, 0, 0);
        if (e.ts < midnight.getTime() / 1000) return false;
      }

      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const pName = (e.product_name || "").toLowerCase();
        const pId = (e.product_id || "").toLowerCase();
        const tId = String(e.product_track_id ?? e.track_id ?? "");
        const sId = (e.session_id || "").toLowerCase();
        const hId = String(e.hand_id ?? "");
        return (
          pName.includes(q) ||
          pId.includes(q) ||
          tId.includes(q) ||
          sId.includes(q) ||
          hId.includes(q)
        );
      }

      return true;
    });
  }, [events?.events, dateRange, searchQuery]);

  return (
    <div className="space-y-6">
      {/* ------------------------------------------------------------ KPI row */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Kpi label="Events" value={stats?.events} />
        <Kpi label="Picked up" value={stats?.picked_up} tone="hand" />
        <Kpi label="Put back" value={stats?.put_back} tone="returning" />
        <Kpi
          label="To confirm"
          value={stats?.pending_total}
          tone={stats?.pending_total ? "basket" : undefined}
        />
        <Kpi label="Checked out" value={stats?.checked_out} tone="ok" />
        <Kpi label="Touch" value={stats?.touch} />
        <Kpi label="Tracks lost" value={stats?.lost} tone="lost" />
        <Kpi
          label="Unaccounted"
          value={stats?.unaccounted}
          tone={stats?.unaccounted ? "lost" : undefined}
        />
      </div>

      {note && (
        <div className="note border-teal-200 bg-mint-200/70 text-[11px] text-teal-700">
          {note}
        </div>
      )}
      {error && (
        <div className="note border-rose-200 bg-rose-200/50 font-mono text-[11px] text-rose-300">
          {error}
        </div>
      )}

      {/* Rank 5: Visual Product Interaction Funnel */}
      <FunnelView
        stats={stats ?? null}
        pendingInHand={pending?.in_hand ?? 0}
        pendingInBasket={pending?.in_basket ?? 0}
      />

      {/* Rank 9: Inventory Heatmap & Loss Prevention Analytics */}
      <LossAnalytics
        events={events?.events ?? []}
        products={products?.products ?? []}
        stats={stats ?? null}
      />

      {/* Operational 3-Column Grid */}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        {/* ------------------------------------------------ products detected */}
        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">Products detected</span>
            <span className="meta">{products?.products.length ?? 0}</span>
          </div>
          <div className="max-h-80 overflow-y-auto">
            <table className="w-full">
              <thead className="sticky top-0 bg-white/95 backdrop-blur">
                <tr className="border-b border-lavender-200">
                  <th className="th">Product</th>
                  <th className="th">Seen</th>
                  <th className="th">Picked</th>
                  <th className="th">Sold</th>
                </tr>
              </thead>
              <tbody>
                {(products?.products ?? []).map((p: ProductRow) => (
                  <tr key={p.product_id} className="border-b border-lavender-200/70">
                    <td className="td font-sans">
                      <div className="text-navy-800">{p.product_name}</div>
                      <div className="text-[9px] text-navy-400">{p.product_id}</div>
                    </td>
                    <td className="td">{p.seen_count}</td>
                    <td className="td">{p.picked_up_count}</td>
                    <td className="td text-teal-600">{p.purchased_count}</td>
                  </tr>
                ))}
                {!products?.products.length && <EmptyRow cols={4} text="No products seen yet." />}
              </tbody>
            </table>
          </div>
        </section>

        {/* --------------------------------------------- pending confirmations */}
        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">Awaiting owner confirmation</span>
            <span className="flex gap-2 font-mono text-[10px]">
              <span className="text-[#A85F3C]">{pending?.in_hand ?? 0} in hand</span>
              <span className="text-[#5F58AE]">{pending?.in_basket ?? 0} in basket</span>
            </span>
          </div>
          <div className="max-h-80 space-y-2 overflow-y-auto p-3">
            {(pending?.pending ?? []).map((e: PendingRow) => {
              const inBasket = e.reason === "in_basket";
              return (
                <div
                  key={e.event_uid}
                  onClick={() => setSelectedIncident({ type: "pending", pending: e })}
                  className={`rounded-2xl border p-3 cursor-pointer transition hover:shadow-md ${
                    inBasket
                      ? "border-[#E0DDF6] bg-[#F4F2FD] hover:border-[#5F58AE]"
                      : "border-[#EEDBCF] bg-[#FBF2EC] hover:border-[#A85F3C]"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-xs font-semibold text-navy-800">
                      {e.product_name}
                    </span>
                    <span
                      className={`chip ${
                        inBasket
                          ? "border-[#E0DDF6] bg-white text-[#5F58AE]"
                          : "border-[#EEDBCF] bg-white text-[#A85F3C]"
                      }`}
                    >
                      {e.live_state ?? (inBasket ? "IN_BASKET" : "IN_HAND")}
                    </span>
                  </div>
                  <div className="mt-1.5 font-mono text-[10px] text-navy-500">
                    picked up {stamp(e.ts)}
                    {e.hand_id != null ? ` · hand ${e.hand_id}` : ""}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <span
                      className="chip border-lavender-300 bg-white text-navy-500"
                      title="Stable identity - survives the track id changing"
                    >
                      {e.product_id}
                    </span>
                    <span
                      className="chip border-lavender-300 bg-white text-navy-500"
                      title="ByteTrack id at the time of this event"
                    >
                      track #{e.product_track_id ?? e.track_id}
                    </span>
                    {e.inferred === 1 && (
                      <span className="chip border-amber-200 bg-amber-200/60 text-amber-600">
                        inferred
                      </span>
                    )}
                  </div>
                  <div className="mt-3 flex gap-2" onClick={(e) => e.stopPropagation()}>
                    <button
                      className="btn btn-primary flex-1 justify-center"
                      onClick={() =>
                        act(`Checked out ${e.product_name}.`, () =>
                          api.checkout({
                            product_id: e.product_id as string,
                            product_name: e.product_name as string,
                            track_id: e.product_track_id ?? (e.track_id as number),
                            session_id: e.session_id,
                            hand_id: e.hand_id,
                            event_uid: e.event_uid,
                            basket_track_id: e.basket_track_id,
                          }),
                        )
                      }
                    >
                      Mark as bought
                    </button>
                    <button
                      className="btn flex-1 justify-center"
                      onClick={() =>
                        act(`${e.product_name} marked as returned.`, () =>
                          api.resolveEvent(
                            e.event_uid,
                            inBasket ? "removed from basket" : "put back by owner",
                          ),
                        )
                      }
                    >
                      Put back
                    </button>
                  </div>
                </div>
              );
            })}
            {!pending?.pending.length && (
              <Empty text="Nothing is waiting for confirmation." />
            )}
          </div>
        </section>

        {/* ------------------------------------------------------------ alerts */}
        <section className="panel-dark">
          <div className="flex items-center justify-between gap-3 border-b border-white/10 px-5 py-3">
            <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-mint-200">
              Alerts / lost
            </span>
            <span className="font-mono text-[10px] text-lavender-300">
              grace {ago(alerts?.grace_seconds)}
            </span>
          </div>
          <div className="max-h-80 space-y-2 overflow-y-auto p-3">
            {(alerts?.alerts ?? []).map((a: Alert) => (
              <div
                key={`${a.kind}-${a.event_uid}`}
                onClick={() => setSelectedIncident({ type: "alert", alert: a })}
                className={`rounded-2xl border p-3 cursor-pointer transition hover:scale-[1.01] ${
                  a.severity === "high"
                    ? "border-rose-400/50 bg-rose-400/10 hover:border-rose-400"
                    : "border-amber-400/40 bg-amber-400/10 hover:border-amber-400"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span
                    className={`chip ${
                      a.severity === "high"
                        ? "border-rose-400/50 bg-rose-400/15 text-[#F5B9B5]"
                        : "border-amber-400/40 bg-amber-400/15 text-[#F0D5A2]"
                    }`}
                  >
                    {a.kind}
                  </span>
                  <span className="font-mono text-[10px] text-lavender-300/80">
                    {ago(a.age_s)} ago
                  </span>
                </div>
                <p className="mt-2 text-[11px] leading-snug text-lavender-100">{a.message}</p>
                <div className="mt-1.5 font-mono text-[9px] text-lavender-300/70">
                  track #{a.track_id} &middot; {clock(a.ts)} &middot; {a.session_id}
                </div>
                <div className="mt-3 flex gap-2" onClick={(e) => e.stopPropagation()}>
                  <button
                    className="btn flex-1 justify-center"
                    onClick={() =>
                      act("Alert acknowledged.", () =>
                        api.resolveEvent(a.event_uid, "acknowledged"),
                      )
                    }
                  >
                    Acknowledge
                  </button>
                  <button
                    className="btn btn-primary flex-1 justify-center"
                    onClick={() =>
                      act(`${a.product_name} marked as sold.`, () =>
                        api.checkout({
                          product_id: a.product_id,
                          product_name: a.product_name,
                          track_id: a.track_id,
                          session_id: a.session_id,
                          note: "confirmed from alert",
                        }),
                      )
                    }
                  >
                    It was sold
                  </button>
                </div>
              </div>
            ))}
            {!alerts?.alerts.length && (
              <Empty
                text="No unresolved situations. Everything picked up is accounted for."
                dark
              />
            )}
          </div>
        </section>
      </div>

      {/* ---------------------------------------------- product identities */}
      <section className="panel">
        <div className="panel-head">
          <span className="panel-title">Product identity vs tracking identity</span>
          <span className="meta">
            {products?.identities.length ?? 0} products /{" "}
            {products?.reassociations.length ?? 0} re-associations
          </span>
        </div>
        <div className="grid grid-cols-1 gap-5 p-4 lg:grid-cols-2">
          <div className="max-h-52 overflow-y-auto overflow-x-auto rounded-xl border border-lavender-200/80">
            <table className="w-full">
              <thead className="sticky top-0 bg-white/95 backdrop-blur z-10">
                <tr className="border-b border-lavender-200">
                  <th className="th !py-1.5">product_id (stable)</th>
                  <th className="th !py-1.5">state</th>
                  <th className="th !py-1.5">current track</th>
                  <th className="th !py-1.5">track ids seen</th>
                </tr>
              </thead>
              <tbody>
                {(products?.identities ?? []).map((p) => (
                  <tr key={p.product_id} className="border-b border-lavender-200/70 hover:bg-lavender-100/50">
                    <td className="td !py-1.5">
                      <span className="font-semibold text-navy-800">{p.product_id}</span>
                      {p.reassociations > 0 && (
                        <span
                          className="ml-1.5 text-[9px] text-teal-600 font-semibold"
                          title="This product was re-identified after its track died"
                        >
                          re-id x{p.reassociations}
                        </span>
                      )}
                    </td>
                    <td className="td !py-1.5">{p.state}</td>
                    <td className="td !py-1.5 text-navy-500">
                      {p.current_track_id != null ? `#${p.current_track_id}` : "-"}
                    </td>
                    <td className="td !py-1.5 text-navy-400">
                      {p.track_ids.map((t) => `#${t}`).join(" ")}
                    </td>
                  </tr>
                ))}
                {!products?.identities.length && (
                  <EmptyRow cols={4} text="No products tracked in this session yet." />
                )}
              </tbody>
            </table>
          </div>

          <div className="max-h-52 overflow-y-auto overflow-x-auto rounded-xl border border-lavender-200/80">
            <div className="sticky top-0 bg-white/95 backdrop-blur z-10 px-4 py-1.5 border-b border-lavender-200 text-[10px] font-semibold uppercase tracking-wider text-navy-500">
              Recent re-identifications
            </div>
            <table className="w-full">
              <thead className="sticky top-7 bg-white/95 backdrop-blur z-10">
                <tr className="border-b border-lavender-200">
                  <th className="th !py-1.5">product</th>
                  <th className="th !py-1.5">track</th>
                  <th className="th !py-1.5">history</th>
                  <th className="th !py-1.5">spatial</th>
                  <th className="th !py-1.5">look</th>
                </tr>
              </thead>
              <tbody>
                {(products?.reassociations ?? []).map((r, i) => (
                  <tr key={`${r.ts}-${i}`} className="border-b border-lavender-200/70 hover:bg-lavender-100/50">
                    <td className="td !py-1.5 font-semibold text-navy-800">{r.product_id}</td>
                    <td className="td !py-1.5 text-navy-500">
                      #{r.from_track} &rarr; #{r.to_track}
                    </td>
                    <td className="td !py-1.5">{r.history ?? "-"}</td>
                    <td className="td !py-1.5">{r.spatial ?? "-"}</td>
                    <td className="td !py-1.5">{r.appearance ?? "-"}</td>
                  </tr>
                ))}
                {!products?.reassociations.length && (
                  <EmptyRow
                    cols={5}
                    text="No track has had to be re-identified yet."
                  />
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* -------------------------------------------------------- ledger table */}
      <section className="space-y-3">
        {/* Rank 6: Search, Filter & Date Range Picker */}
        <LedgerFilterBar
          search={searchQuery}
          onSearchChange={setSearchQuery}
          selectedType={filterType}
          onTypeChange={setFilterType}
          dateRange={dateRange}
          onDateRangeChange={setDateRange}
          events={filteredEvents}
          filteredCount={filteredEvents.length}
          totalCount={events?.total ?? 0}
        />

        <div className="panel overflow-hidden">
          <div className="max-h-[50vh] overflow-auto">
            <table className="w-full">
              <thead className="sticky top-0 bg-white/95 backdrop-blur">
                <tr className="border-b border-lavender-200">
                  <th className="th">Time</th>
                  <th className="th">Event</th>
                  <th className="th">Product</th>
                  <th className="th">Identity</th>
                  <th className="th">Track</th>
                  <th className="th">Basket</th>
                  <th className="th">Hand</th>
                  <th className="th">State</th>
                  <th className="th">Displacement</th>
                  <th className="th">Dwell</th>
                  <th className="th">Session</th>
                  <th className="th">Action</th>
                </tr>
              </thead>
              <tbody>
                {filteredEvents.map((e: LedgerEvent) => (
                  <tr
                    key={e.event_uid}
                    onClick={() => setSelectedIncident({ type: "event", event: e })}
                    className="border-b border-lavender-200/70 hover:bg-lavender-100 cursor-pointer transition"
                  >
                    <td className="td whitespace-nowrap">{clock(e.ts)}</td>
                    <td className="td">
                      <EventBadge type={e.type} />
                    </td>
                    <td className="td font-medium text-navy-800">{e.product_name}</td>
                    <td className="td text-navy-500">{e.product_id}</td>
                    <td className="td text-navy-500">
                      #{e.product_track_id ?? e.track_id}
                    </td>
                    <td className="td">
                      {e.basket_track_id != null ? (
                        <span className="text-[#5F58AE]">#{e.basket_track_id}</span>
                      ) : (
                        <span className="text-navy-400">-</span>
                      )}
                      {e.inferred === 1 && (
                        <span
                          className="ml-1 text-[9px] text-amber-600"
                          title="Inferred from interaction history, not directly observed"
                        >
                          inf
                        </span>
                      )}
                    </td>
                    <td className="td text-navy-500">{e.hand_id ?? "-"}</td>
                    <td className="td text-navy-500">
                      {e.state_from ? `${e.state_from}->${e.state}` : e.state}
                    </td>
                    <td className="td">
                      {typeof e.meta?.displacement_px === "number"
                        ? `${e.meta.displacement_px}px`
                        : "-"}
                    </td>
                    <td className="td">
                      {e.dwell_ms ? `${(e.dwell_ms / 1000).toFixed(1)}s` : "-"}
                    </td>
                    <td className="td text-navy-400">{e.session_id}</td>
                    <td className="td" onClick={(ev) => ev.stopPropagation()}>
                      {e.resolved ? (
                        <span className="text-teal-600 font-semibold">
                          {e.resolution ?? "resolved"}
                        </span>
                      ) : (
                        <button
                          className="text-navy-600 hover:text-teal-600 underline font-medium text-xs"
                          onClick={() => setSelectedIncident({ type: "event", event: e })}
                        >
                          Review
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {!filteredEvents.length && (
                  <EmptyRow
                    cols={12}
                    text={
                      searchQuery || dateRange !== "all" || filterType
                        ? "No events match your current filter."
                        : "No events recorded yet."
                    }
                  />
                )}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between border-t border-lavender-200 bg-lavender-100/60 px-4 py-2.5 font-mono text-[10px] text-navy-500">
            <span>
              showing {filteredEvents.length} of {events?.total ?? 0} events
            </span>
            <span>{purchases?.purchases.length ?? 0} recorded sales</span>
          </div>
        </div>
      </section>

      {/* ----------------------------------------------------------- sessions */}
      <section className="panel">
        <div className="panel-head">
          <span className="panel-title">Camera sessions</span>
        </div>
        <div className="max-h-56 overflow-y-auto">
          <table className="w-full">
            <thead className="sticky top-0 bg-white/95 backdrop-blur">
              <tr className="border-b border-lavender-200">
                <th className="th">Session</th>
                <th className="th">Source</th>
                <th className="th">Started</th>
                <th className="th">Ended</th>
              </tr>
            </thead>
            <tbody>
              {(sessions?.sessions ?? []).map((s: SessionRow) => (
                <tr key={s.id} className="border-b border-lavender-200/70">
                  <td className="td">{s.id}</td>
                  <td className="td text-navy-500">{s.source}</td>
                  <td className="td">{stamp(s.started_at)}</td>
                  <td className="td">{s.ended_at ? stamp(s.ended_at) : "active"}</td>
                </tr>
              ))}
              {!sessions?.sessions.length && <EmptyRow cols={4} text="No sessions yet." />}
            </tbody>
          </table>
        </div>
      </section>

      {/* Rank 7: Incident Quick-Action Drawer */}
      <IncidentDrawer
        target={selectedIncident}
        onClose={() => setSelectedIncident(null)}
        onCheckout={async (item) => {
          await act(`Checked out ${item.product_name}.`, () =>
            api.checkout({
              product_id: item.product_id,
              product_name: item.product_name,
              track_id: item.track_id,
              session_id: item.session_id,
              event_uid: item.event_uid,
            }),
          );
        }}
        onResolve={async (uid, reason) => {
          await act(`Resolved event: ${reason}.`, () => api.resolveEvent(uid, reason));
        }}
      />
    </div>
  );
}

const TONE: Record<string, string> = {
  hand: "text-[#A85F3C]",
  returning: "text-[#4A6BA5]",
  basket: "text-[#5F58AE]",
  ok: "text-teal-600",
  lost: "text-rose-300",
};

function Kpi({
  label,
  value,
  tone,
}: {
  label: string;
  value?: number;
  tone?: keyof typeof TONE;
}) {
  return (
    <div className="panel px-4 py-3">
      <div className="text-[9px] font-semibold uppercase tracking-[0.14em] text-navy-400">
        {label}
      </div>
      <div
        className={`mt-1 font-mono text-2xl font-semibold ${
          tone ? TONE[tone] : "text-navy-800"
        }`}
      >
        {value ?? 0}
      </div>
    </div>
  );
}

function Empty({ text, dark }: { text: string; dark?: boolean }) {
  return (
    <div
      className={`px-2 py-8 text-center text-[11px] ${
        dark ? "text-lavender-300/80" : "text-navy-400"
      }`}
    >
      {text}
    </div>
  );
}

function EmptyRow({ cols, text }: { cols: number; text: string }) {
  return (
    <tr>
      <td colSpan={cols} className="px-3 py-8 text-center text-[11px] text-navy-400">
        {text}
      </td>
    </tr>
  );
}
