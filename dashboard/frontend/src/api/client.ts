import axios from "axios";

/**
 * API base resolution:
 * - VITE_API_BASE is honored when set (custom deployments).
 * - Otherwise we use the same origin as the page; in development the
 *   Vite dev server proxies /api, /ws and /auth to the backend, so
 *   the dashboard works from any host it is served on.
 */
export const API_BASE: string = (import.meta.env.VITE_API_BASE || "").replace(/\/+$/, "");

export interface Me {
  id: string;
  username: string;
  avatar?: string | null;
  roles?: string[];
}

export interface Feature {
  name: string;
  description: string;
  enabled_globally: boolean;
  enabled_per_guild: Record<string, boolean>;
  updated_at?: string | null;
  updated_by?: string | null;
}

export interface Guild {
  guild_id: string;
  name: string;
  member_count?: number | null;
  icon?: string | null;
  joined_at?: string | null;
}

export interface LogEntry {
  id?: string | number;
  actor_id?: string | null;
  action: string;
  target?: string | null;
  details?: unknown;
  level?: string;
  timestamp: string;
}

export interface UsageSummary {
  period: string;
  total_commands: number;
  unique_users: number;
  commands_by_name: Record<string, number>;
}

export interface ServiceStatus {
  up: boolean;
  configured: boolean;
}

export interface BotHealth {
  status: string;
  services: {
    redis: ServiceStatus;
    database: ServiceStatus;
    bot_online: boolean;
  };
  bot: {
    uptime_seconds?: number;
    latency_ms?: number;
    guild_count?: number;
    user_count?: number;
    loaded_cogs?: string[];
    maintenance_mode?: boolean;
    reported_at?: string | null;
  };
}

const http = axios.create({
  baseURL: API_BASE,
  timeout: 10_000,
  withCredentials: true,
});

async function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const res = await http.get<T>(url, { params });
  return res.data;
}

async function post<T>(url: string, body: unknown): Promise<T> {
  const res = await http.post<T>(url, body);
  return res.data;
}

export const api = {
  fetchMe: () => get<Me>("/api/me").catch(() => null),

  fetchFeatures: () => get<Feature[]>("/api/features"),
  upsertFeature: (feature: Partial<Feature> & { name: string }) =>
    post<{ ok: boolean }>("/api/features", feature),
  batchFeatures: (features: Array<Partial<Feature> & { name: string }>) =>
    post<{ ok: boolean }>("/api/features/batch", { features }),

  fetchGuilds: () => get<Guild[]>("/api/guilds"),
  fetchGuildStats: (guildId: string) =>
    get<{ commands_30d: number; unique_users: number; top_commands: Array<{ command: string; count: number }> }>(
      `/api/guilds/${encodeURIComponent(guildId)}/stats`,
    ),

  fetchLogs: (params?: Record<string, unknown>) => get<LogEntry[]>("/api/logs", params),
  fetchErrors: (params?: Record<string, unknown>) => get<LogEntry[]>("/api/errors", params),

  fetchUsage: (from: string, to: string) =>
    get<UsageSummary>("/api/usage", { from, to }),

  sendControl: (action: string, actorId?: string, reason?: string) =>
    post<{ ok: boolean }>("/api/control", { action, actor_id: actorId, reason }),

  fetchBotHealth: () => get<BotHealth>("/api/bot/health").catch(() => null),
  fetchBotStatus: () => get<Record<string, unknown>>("/api/bot/status"),

  fetchAdmins: () => get<Array<{ id: string; username: string; role: string }>>("/api/admins"),
  addAdmin: (discordId: string, username: string) =>
    post<{ ok: boolean }>("/api/admins", { discord_id: discordId, username }),
};

/** Live log stream over WebSocket (same-origin, proxied in dev). */
export function connectLogStream(
  onMessage: (entry: LogEntry) => void,
  onStatus: (connected: boolean) => void,
): () => void {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const base = API_BASE ? API_BASE.replace(/^http/, "ws") : `${proto}//${window.location.host}`;
  let ws: WebSocket | null = null;
  let closed = false;
  let retry = 0;

  const connect = () => {
    if (closed) return;
    ws = new WebSocket(`${base}/ws/logs`);
    ws.onopen = () => {
      retry = 0;
      onStatus(true);
    };
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string);
        if (data && typeof data === "object" && "action" in data) {
          onMessage(data as LogEntry);
        }
      } catch {
        /* ignore non-JSON frames */
      }
    };
    ws.onclose = () => {
      onStatus(false);
      if (!closed) {
        retry = Math.min(retry + 1, 5);
        setTimeout(connect, 1000 * retry);
      }
    };
    ws.onerror = () => ws?.close();
  };

  connect();

  return () => {
    closed = true;
    ws?.close();
  };
}