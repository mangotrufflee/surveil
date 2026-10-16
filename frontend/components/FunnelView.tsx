"use client";

import type { Stats } from "@/lib/api";

interface FunnelViewProps {
  stats: Stats | null;
  pendingInHand: number;
  pendingInBasket: number;
}

export default function FunnelView({
  stats,
  pendingInHand,
  pendingInBasket,
}: FunnelViewProps) {
  const touches = stats?.touch ?? 0;
  const pickedUp = stats?.picked_up ?? 0;
  const inPending = pendingInHand + pendingInBasket;
  const checkedOut = stats?.checked_out ?? 0;
  const putBack = stats?.put_back ?? 0;
  const lost = (stats?.lost ?? 0) + (stats?.unaccounted ?? 0);

  // Total shelf touch opportunities
  const totalIntent = Math.max(touches + pickedUp, 1);
  const pickupRate = Math.round((pickedUp / totalIntent) * 100);
  const checkoutFromPickup = pickedUp > 0 ? Math.round((checkedOut / pickedUp) * 100) : 0;
  const returnRate = pickedUp > 0 ? Math.round((putBack / pickedUp) * 100) : 0;
  const shrinkRate = pickedUp > 0 ? Math.round((lost / pickedUp) * 100) : 0;

  const stages = [
    {
      id: "browse",
      title: "Shelf Touches & Engagements",
      count: touches + pickedUp,
      rate: "100%",
      sub: `${touches} touch-only · ${pickedUp} lifted`,
      color: "bg-teal-500",
      lightColor: "bg-teal-100 text-teal-800 border-teal-200",
    },
    {
      id: "picked",
      title: "Picked Up from Shelf",
      count: pickedUp,
      rate: `${pickupRate}% conversion`,
      sub: `${putBack} returned to shelf (${returnRate}%)`,
      color: "bg-amber-500",
      lightColor: "bg-amber-100 text-amber-800 border-amber-200",
    },
    {
      id: "cart",
      title: "In-Hand / Shopping Basket",
      count: inPending,
      rate: `${pickedUp > 0 ? Math.round((inPending / pickedUp) * 100) : 0}% active`,
      sub: `${pendingInBasket} basket · ${pendingInHand} hand`,
      color: "bg-purple-500",
      lightColor: "bg-purple-100 text-purple-800 border-purple-200",
    },
    {
      id: "sold",
      title: "Checked Out & Reconciled",
      count: checkedOut,
      rate: `${checkoutFromPickup}% purchase rate`,
      sub: "Confirmed sold at checkout",
      color: "bg-emerald-500",
      lightColor: "bg-emerald-100 text-emerald-800 border-emerald-200",
    },
  ];

  return (
    <section className="panel p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-lavender-200">
        <div>
          <h3 className="panel-title">Product Interaction Funnel</h3>
          <p className="text-xs text-navy-500 mt-0.5">
            Real-time conversion from shelf touch to checkout & loss detection
          </p>
        </div>
        <div className="flex items-center gap-2">
          {lost > 0 ? (
            <span className="chip border-rose-300 bg-rose-100 text-rose-700 animate-pulse font-mono">
              ⚠ {lost} Unaccounted / Lost ({shrinkRate}% shrink)
            </span>
          ) : (
            <span className="chip border-emerald-200 bg-mint-100 text-teal-700 font-mono">
              ✓ 0 Unaccounted Loss
            </span>
          )}
        </div>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-4">
        {stages.map((stage, idx) => {
          const maxVal = Math.max(stages[0].count, 1);
          const widthPct = Math.max(12, Math.round((stage.count / maxVal) * 100));

          return (
            <div
              key={stage.id}
              className="relative flex flex-col justify-between rounded-2xl border border-lavender-200 bg-white/70 p-4 shadow-sm"
            >
              <div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-navy-400">
                    Step 0{idx + 1}
                  </span>
                  <span className={`chip text-[10px] ${stage.lightColor}`}>
                    {stage.rate}
                  </span>
                </div>
                <div className="mt-2 text-2xl font-bold tracking-tight text-navy-800">
                  {stage.count}
                </div>
                <div className="mt-0.5 text-xs font-semibold text-navy-700">
                  {stage.title}
                </div>
                <div className="mt-1 text-[11px] text-navy-400 font-mono">
                  {stage.sub}
                </div>
              </div>

              {/* Progress bar visual */}
              <div className="mt-4 pt-3 border-t border-lavender-100">
                <div className="h-2 w-full overflow-hidden rounded-full bg-lavender-200">
                  <div
                    className={`h-full rounded-full ${stage.color} transition-all duration-500`}
                    style={{ width: `${widthPct}%` }}
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
