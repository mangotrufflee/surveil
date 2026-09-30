"use client";

import { useCallback, useState } from "react";
import {
  api,
  LEDGER_EXPORT_URL,
  type Alert,
  type LedgerEvent,
  type ProductRow,
  type SessionRow,
  type Stats,
} from "@/lib/api";
import { usePolling } from "@/lib/usePolling";
import { EventBadge } from "@/components/Badges";
import { ago, clock, stamp } from "@/lib/format";

const EVENT_FILTERS = [
  "",
  "PICKED_UP",
  "PUT_BACK",
  "PLACED_IN_BASKET",
  "CHECKED_OUT",
  "TOUCH",
  "TRACK_LOST",
];

export default function OwnerDashboard() {
  const [filter, setFilter] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: stats } = usePolling<Stats>(() => api.stats(), 2000);
  const { data: basket } = usePolling(() => api.basket(), 2000);
  const { data: purchases } = usePolling(() => api.purchases(), 4000);
  const { data: alerts } = usePolling(() => api.alerts(), 3000);
  const { data: products } = usePolling(() => api.products(), 5000);
  const { data: sessions } = usePolling(() => api.sessions(), 8000);
  const { data: events, refresh: refreshEvents } = usePolling(
    () => api.events({ limit: 100, type: filter || undefined }),
    3000,
    [filter],
  );

  const act = useCallback(
    async (label: string, fn: () => Promise<unknown>) => {
      setError(null);
      setNote(null);
      try {
        await fn();
        setNote(label);
        refreshEvents();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [refreshEvents],
  );

  return (
    <div className="space-y-4">
      {/* ------------------------------------------------------------ KPI row */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Kpi label="Events" value={stats?.events} />
        <Kpi label="Picked up" value={stats?.picked_up} tone="hand" />
        <Kpi label="Put back" value={stats?.put_back} tone="returning" />
        <Kpi label="In basket" value={stats?.pending_basket} tone="basket" />
        <Kpi label="Checked out" value={stats?.checked_out} tone="ok" />
        <Kpi label="Touch" value={stats?.touch} />
        <Kpi label="Tracks lost" value={stats?.lost} tone="lost" />
        <Kpi label="Unaccounted" value={stats?.unaccounted} tone={stats?.unaccounted ? "lost" : undefined} />
      </div>

      {note && (
        <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 font-mono text-[11px] text-emerald-300">
          {note}
        </div>
      )}
      {error && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 font-mono text-[11px] text-rose-300">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {/* ------------------------------------------------ products detected */}
        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">Products detected</span>
            <span className="font-mono text-[10px] text-slate-500">
              {products?.products.length ?? 0}
            </span>
          </div>
          <div className="max-h-80 overflow-y-auto">
            <table className="w-full">
              <thead className="sticky top-0 bg-ink-900">
                <tr className="border-b border-ink-700">
                  <th className="th">Product</th>
                  <th className="th">Seen</th>
                  <th className="th">Picked</th>
                  <th className="th">Sold</th>
                </tr>
              </thead>
              <tbody>
                {(products?.products ?? []).map((p: ProductRow) => (
                  <tr key={p.product_id} className="border-b border-ink-800/60">
                    <td className="td">
                      <div className="text-slate-200">{p.product_name}</div>
                      <div className="text-[9px] text-slate-600">{p.product_id}</div>
                    </td>
                    <td className="td">{p.seen_count}</td>
                    <td className="td">{p.picked_up_count}</td>
                    <td className="td text-emerald-400">{p.purchased_count}</td>
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
            <span className="font-mono text-[10px] text-state-basket">
              {basket?.pending.length ?? 0}
            </span>
          </div>
          <div className="max-h-80 space-y-1.5 overflow-y-auto p-2">
            {(basket?.pending ?? []).map((e: LedgerEvent) => (
              <div
                key={e.event_uid}
                className="rounded-lg border border-state-basket/25 bg-state-basket/5 p-2.5"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-slate-100">
                    {e.product_name}
                  </span>
                  <span className="font-mono text-[10px] text-slate-500">#{e.track_id}</span>
                </div>
                <div className="mt-1 font-mono text-[10px] text-slate-500">
                  basket {stamp(e.ts)} &middot; session {e.session_id ?? "-"}
                  {e.hand_id != null ? ` · hand ${e.hand_id}` : ""}
                </div>
                <button
                  className="btn btn-primary mt-2 w-full justify-center"
                  onClick={() =>
                    act(`Checked out ${e.product_name}.`, () =>
                      api.checkout({
                        product_id: e.product_id as string,
                        product_name: e.product_name as string,
                        track_id: e.track_id as number,
                        session_id: e.session_id,
                        hand_id: e.hand_id,
                      }),
                    )
                  }
                >
                  Confirm checkout
                </button>
              </div>
            ))}
            {!basket?.pending.length && (
              <Empty text="Nothing in the basket is waiting for confirmation." />
            )}
          </div>
        </section>

        {/* ------------------------------------------------------------ alerts */}
        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">Alerts / lost</span>
            <span className="font-mono text-[10px] text-slate-500">
              grace {ago(alerts?.grace_seconds)}
            </span>
          </div>
          <div className="max-h-80 space-y-1.5 overflow-y-auto p-2">
            {(alerts?.alerts ?? []).map((a: Alert) => (
              <div
                key={`${a.kind}-${a.event_uid}`}
                className={`rounded-lg border p-2.5 ${
                  a.severity === "high"
                    ? "border-state-lost/30 bg-state-lost/5"
                    : "border-amber-500/25 bg-amber-500/5"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span
                    className={`chip ${
                      a.severity === "high"
                        ? "border-state-lost/40 bg-state-lost/10 text-state-lost"
                        : "border-amber-500/40 bg-amber-500/10 text-amber-300"
                    }`}
                  >
                    {a.kind}
                  </span>
                  <span className="font-mono text-[10px] text-slate-500">
                    {ago(a.age_s)} ago
                  </span>
                </div>
                <p className="mt-1.5 text-[11px] leading-snug text-slate-300">{a.message}</p>
                <div className="mt-1.5 font-mono text-[9px] text-slate-600">
                  track #{a.track_id} &middot; {clock(a.ts)} &middot; {a.session_id}
                </div>
                <div className="mt-2 flex gap-1.5">
                  <button
                    className="btn flex-1 justify-center"
                    onClick={() =>
                      act("Alert acknowledged.", () => api.resolveEvent(a.event_uid, "acknowledged"))
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
              <Empty text="No unresolved situations. Everything picked up is accounted for." />
            )}
          </div>
        </section>
      </div>

      {/* -------------------------------------------------------- ledger table */}
      <section className="panel">
        <div className="panel-head">
          <span className="panel-title">Product interaction ledger</span>
          <div className="flex items-center gap-2">
            <select className="field w-44" value={filter} onChange={(e) => setFilter(e.target.value)}>
              {EVENT_FILTERS.map((f) => (
                <option key={f || "all"} value={f}>
                  {f || "all events"}
                </option>
              ))}
            </select>
            <a
              className="btn"
              href={`${LEDGER_EXPORT_URL}${filter ? `?type=${filter}` : ""}`}
              download
            >
              Export CSV
            </a>
          </div>
        </div>
        <div className="max-h-[46vh] overflow-auto">
          <table className="w-full">
            <thead className="sticky top-0 bg-ink-900">
              <tr className="border-b border-ink-700">
                <th className="th">Time</th>
                <th className="th">Event</th>
                <th className="th">Product</th>
                <th className="th">Track</th>
                <th className="th">Hand</th>
                <th className="th">State</th>
                <th className="th">Displacement</th>
                <th className="th">Dwell</th>
                <th className="th">Session</th>
                <th className="th">Status</th>
              </tr>
            </thead>
            <tbody>
              {(events?.events ?? []).map((e: LedgerEvent) => (
                <tr key={e.event_uid} className="border-b border-ink-800/60 hover:bg-ink-850/50">
                  <td className="td whitespace-nowrap">{clock(e.ts)}</td>
                  <td className="td">
                    <EventBadge type={e.type} />
                  </td>
                  <td className="td">{e.product_name}</td>
                  <td className="td text-slate-500">#{e.track_id}</td>
                  <td className="td text-slate-500">{e.hand_id ?? "-"}</td>
                  <td className="td text-slate-500">
                    {e.state_from ? `${e.state_from}->${e.state}` : e.state}
                  </td>
                  <td className="td">
                    {typeof e.meta?.displacement_px === "number"
                      ? `${e.meta.displacement_px}px`
                      : "-"}
                  </td>
                  <td className="td">{e.dwell_ms ? `${(e.dwell_ms / 1000).toFixed(1)}s` : "-"}</td>
                  <td className="td text-slate-600">{e.session_id}</td>
                  <td className="td">
                    {e.resolved ? (
                      <span className="text-emerald-400">{e.resolution ?? "resolved"}</span>
                    ) : (
                      <button
                        className="text-slate-500 underline decoration-dotted hover:text-slate-300"
                        onClick={() =>
                          act("Event acknowledged.", () =>
                            api.resolveEvent(e.event_uid, "acknowledged"),
                          )
                        }
                      >
                        acknowledge
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {!events?.events.length && <EmptyRow cols={10} text="No events recorded yet." />}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between border-t border-ink-700 px-3 py-1.5 font-mono text-[10px] text-slate-500">
          <span>
            showing {events?.count ?? 0} of {events?.total ?? 0} events
          </span>
          <span>{(purchases?.purchases.length ?? 0)} recorded sales</span>
        </div>
      </section>

      {/* ----------------------------------------------------------- sessions */}
      <section className="panel">
        <div className="panel-head">
          <span className="panel-title">Camera sessions</span>
        </div>
        <div className="max-h-56 overflow-y-auto">
          <table className="w-full">
            <thead className="sticky top-0 bg-ink-900">
              <tr className="border-b border-ink-700">
                <th className="th">Session</th>
                <th className="th">Source</th>
                <th className="th">Started</th>
                <th className="th">Ended</th>
              </tr>
            </thead>
            <tbody>
              {(sessions?.sessions ?? []).map((s: SessionRow) => (
                <tr key={s.id} className="border-b border-ink-800/60">
                  <td className="td">{s.id}</td>
                  <td className="td text-slate-500">{s.source}</td>
                  <td className="td">{stamp(s.started_at)}</td>
                  <td className="td">{s.ended_at ? stamp(s.ended_at) : "active"}</td>
                </tr>
              ))}
              {!sessions?.sessions.length && <EmptyRow cols={4} text="No sessions yet." />}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

const TONE: Record<string, string> = {
  hand: "text-state-hand",
  returning: "text-state-returning",
  basket: "text-state-basket",
  ok: "text-emerald-400",
  lost: "text-state-lost",
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
    <div className="panel px-3 py-2.5">
      <div className="text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-500">
        {label}
      </div>
      <div className={`mt-0.5 font-mono text-2xl font-semibold ${tone ? TONE[tone] : "text-slate-200"}`}>
        {value ?? 0}
      </div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="px-2 py-6 text-center text-[11px] text-slate-600">{text}</div>;
}

function EmptyRow({ cols, text }: { cols: number; text: string }) {
  return (
    <tr>
      <td colSpan={cols} className="px-3 py-6 text-center text-[11px] text-slate-600">
        {text}
      </td>
    </tr>
  );
}
