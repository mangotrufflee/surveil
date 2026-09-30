export const API_BASE =
  (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export const STREAM_URL = `${API_BASE}/api/stream`;
export const SNAPSHOT_URL = `${API_BASE}/api/snapshot.jpg`;
export const LEDGER_EXPORT_URL = `${API_BASE}/api/ledger/export.csv`;

async function get<T>(path: string, revalidate = 0): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: revalidate ? "force-cache" : "no-store" });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} ${detail.slice(0, 200)}`);
  }
  return res.json() as Promise<T>;
}

async function send<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} ${detail.slice(0, 200)}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => get<Health>("/api/health"),
  config: () => get<AppConfig>("/api/config"),

  live: () => get<LiveSnapshot>("/api/live"),
  status: () => get<PipelineStatus>("/api/pipeline/status"),
  start: (source?: string) => send<PipelineStatus>("/api/pipeline/start", "POST", { source }),
  stop: () => send<PipelineStatus>("/api/pipeline/stop", "POST"),
  restart: (source?: string) =>
    send<PipelineStatus>("/api/pipeline/restart", "POST", { source }),

  setBasketRoi: (roi: number[] | null) =>
    send<{ basket_roi: number[] | null }>("/api/settings/basket-roi", "POST", { roi }),
  setThresholds: (patch: Record<string, number | boolean>) =>
    send<{ thresholds: Thresholds }>("/api/settings/thresholds", "PATCH", patch),

  events: (params: EventQuery) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
    });
    return get<{ events: LedgerEvent[]; count: number; total: number }>(`/api/events?${q}`);
  },
  stats: () => get<Stats>("/api/stats"),
  products: () => get<{ products: ProductRow[] }>("/api/products"),
  alerts: () => get<{ alerts: Alert[]; grace_seconds: number }>("/api/alerts"),
  basket: () => get<{ pending: LedgerEvent[] }>("/api/basket"),
  purchases: () => get<{ purchases: LedgerEvent[] }>("/api/purchases"),
  sessions: () => get<{ sessions: SessionRow[] }>("/api/sessions"),

  checkout: (body: {
    product_id: string;
    product_name: string;
    track_id: number;
    session_id?: string | null;
    hand_id?: number | null;
    note?: string;
  }) => send<{ ok: boolean; purchase: LedgerEvent }>("/api/checkout", "POST", body),

  resolveEvent: (uid: string, resolution: string) =>
    send<{ ok: boolean }>(`/api/events/${uid}/resolve`, "POST", { resolution }),
};

// ------------------------------------------------------------------- types
export type ProductState =
  | "ON_SHELF"
  | "LIFTING"
  | "IN_HAND"
  | "RETURNING"
  | "IN_BASKET"
  | "LOST";

export type EventType =
  | "TOUCH"
  | "PICKED_UP"
  | "PUT_BACK"
  | "PLACED_IN_BASKET"
  | "CHECKED_OUT"
  | "TRACK_LOST"
  | "ALERT_RAISED";

export interface BBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface Health {
  ok: boolean;
  app: string;
  pipeline_running: boolean;
  db: string;
  yolo_model: string;
  hand_backend: string;
  hand_model: string;
  hand_model_present: boolean;
}

export interface Thresholds {
  shelf_displacement_px: number;
  settle_frames: number;
  settle_motion_px: number;
  hand_touch_px: number;
  hand_touch_min_overlap: number;
  lift_confirm_frames: number;
  return_confirm_frames: number;
  basket_overlap_ratio: number;
  basket_confirm_frames: number;
  touch_emit_frames: number;
  max_missed_frames: number;
  mark_lost_state: boolean;
  lost_emit_event: boolean;
}

export interface Transition {
  from: string;
  to: string;
  when: string;
}

export interface AppConfig {
  settings: Record<string, unknown>;
  thresholds: Thresholds;
  state_machine: {
    states: string[];
    events: string[];
    transitions: Transition[];
    always_events: { event: string; when: string }[];
  };
}

export interface PipelineStatus {
  running: boolean;
  session_id: string | null;
  frame: number;
  fps: number;
  started_at: number | null;
  uptime_s: number;
  error: string | null;
  model: string;
  hand_backend: string;
  product_classes: string[];
  ignored_classes: string[];
  basket_mode: string;
  processed_frames: number;
  camera_source: string;
}

export interface ProductTrack {
  track_id: number;
  class_name: string;
  score: number;
  box: [number, number, number, number];
  predicted: boolean;
  time_since_update: number;
}

export interface TrackState {
  track_id: number;
  product_id: string;
  product_name: string;
  state: ProductState;
  anchor: [number, number, number, number] | null;
  anchor_confirmed: boolean;
  settle_frames: number;
  box: [number, number, number, number] | null;
  score: number;
  touching: boolean;
  displaced: boolean;
  displacement_px: number;
  basket_overlap: number;
  hand_id: number | null;
  session_id: string | null;
  lift_frames: number;
  return_frames: number;
  basket_frames: number;
  missed_frames: number;
  age_s: number;
  in_state_s: number;
  picked_up_at: number | null;
}

export interface HandRow {
  hand_id: number;
  customer_id: string;
  session_id: string;
  box: [number, number, number, number];
  score: number;
  hits: number;
  age_s: number;
}

export interface LiveEvent {
  event_uid: string;
  type: EventType;
  ts: number;
  product_id: string;
  product_name: string;
  track_id: number;
  hand_id: number | null;
  session_id: string | null;
  confidence: number;
  box: [number, number, number, number];
  state: ProductState;
  meta: Record<string, unknown>;
}

export interface LiveSnapshot {
  running: boolean;
  session_id: string | null;
  frame: number;
  fps: number;
  timestamp: number;
  frame_size: [number, number];
  products: ProductTrack[];
  hands: HandRow[];
  basket_zone: [number, number, number, number] | null;
  basket_source: string;
  ignored_count: number;
  ignored_classes: string[];
  states: Record<string, TrackState>;
  hud: Record<string, number | string>;
  recent_events: LiveEvent[];
  thresholds: Thresholds;
}

export interface LedgerEvent {
  event_uid: string;
  ts: number;
  ts_iso: string;
  session_id: string | null;
  type: EventType;
  product_id: string | null;
  product_name: string | null;
  track_id: number | null;
  hand_id: number | null;
  confidence: number | null;
  x1: number | null;
  y1: number | null;
  x2: number | null;
  y2: number | null;
  state: string | null;
  state_from: string | null;
  dwell_ms: number | null;
  meta: Record<string, unknown>;
  resolved: 0 | 1;
  resolution: string | null;
  resolved_by: string | null;
}

export interface EventQuery {
  limit?: number;
  offset?: number;
  type?: string;
  product_id?: string;
  session_id?: string;
  resolved?: boolean;
}

export interface Stats {
  events: number;
  picked_up: number;
  put_back: number;
  placed_in_basket: number;
  checked_out: number;
  touch: number;
  lost: number;
  unaccounted: number;
  pending_basket: number;
}

export interface ProductRow {
  product_id: string;
  product_name: string;
  first_seen: number;
  last_seen: number;
  seen_count: number;
  picked_up_count: number;
  purchased_count: number;
  last_pickup: number | null;
}

export interface Alert {
  kind: string;
  severity: string;
  event_uid: string;
  product_id: string;
  product_name: string;
  track_id: number;
  session_id: string | null;
  ts: number;
  ts_iso: string;
  age_s: number;
  message: string;
}

export interface SessionRow {
  id: string;
  source: string;
  started_at: number;
  ended_at: number | null;
  meta: string | null;
}
