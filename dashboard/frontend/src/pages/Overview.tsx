import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Activity, Cpu, Server, ToggleLeft } from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import { api } from "../api/client";
import ChartCard from "../components/ChartCard";

function StatCard({
  label,
  value,
  icon: Icon,
  hint,
}: {
  label: string;
  value: string | number;
  icon: typeof Activity;
  hint?: string;
}) {
  return (
    <div className="card p-5">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-gray-500 dark:text-gray-400">{label}</p>
        <Icon className="h-4 w-4 text-lunar-500" />
      </div>
      <p className="mt-2 text-2xl font-bold text-gray-900 dark:text-gray-100">{value}</p>
      {hint ? <p className="mt-1 text-xs text-gray-400">{hint}</p> : null}
    </div>
  );
}

export default function Overview() {
  const features = useQuery({ queryKey: ["features"], queryFn: api.fetchFeatures });
  const guilds = useQuery({ queryKey: ["guilds"], queryFn: api.fetchGuilds });
  const health = useQuery({ queryKey: ["bot-health"], queryFn: api.fetchBotHealth, refetchInterval: 10_000 });

  const today = new Date().toISOString().slice(0, 10);
  const weekAgo = new Date(Date.now() - 6 * 86400_000).toISOString().slice(0, 10);
  const usage = useQuery({
    queryKey: ["usage", weekAgo, today],
    queryFn: () => api.fetchUsage(weekAgo, today),
  });

  const enabledFeatures = features.data?.filter((f) => f.enabled_globally).length ?? 0;
  const memberCount = guilds.data?.reduce((sum, g) => sum + (g.member_count ?? 0), 0) ?? 0;
  const bot = health.data?.bot;
  const services = health.data?.services;
  const topCommands = Object.entries(usage.data?.commands_by_name ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([command, count]) => ({ command, count }));

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Active Features"
          value={features.data ? `${enabledFeatures}/${features.data.length}` : "—"}
          icon={ToggleLeft}
          hint="Globally enabled"
        />
        <StatCard
          label="Guilds"
          value={guilds.data?.length ?? "—"}
          icon={Server}
          hint={`${memberCount.toLocaleString()} members`}
        />
        <StatCard
          label="Commands (7d)"
          value={usage.data?.total_commands?.toLocaleString() ?? "—"}
          icon={Activity}
          hint={`${usage.data?.unique_users?.toLocaleString() ?? "—"} unique users`}
        />
        <StatCard
          label="Bot Uptime"
          value={bot?.uptime_seconds != null ? `${Math.floor(bot.uptime_seconds / 3600)}h ${Math.floor((bot.uptime_seconds % 3600) / 60)}m` : "—"}
          icon={Cpu}
          hint={bot?.latency_ms != null ? `${bot.latency_ms}ms gateway latency` : "No status report"}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <ChartCard title="Top Commands" subtitle="Last 7 days">
            {topCommands.length === 0 ? (
              <p className="py-10 text-center text-sm text-gray-500 dark:text-gray-400">
                No command usage recorded yet.
              </p>
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={topCommands} layout="vertical" margin={{ left: 8, right: 16 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.1} />
                  <XAxis type="number" stroke="currentColor" opacity={0.5} fontSize={12} />
                  <YAxis
                    type="category"
                    dataKey="command"
                    width={90}
                    stroke="currentColor"
                    opacity={0.7}
                    fontSize={12}
                  />
                  <Tooltip cursor={{ fill: "currentColor", opacity: 0.05 }} />
                  <Bar dataKey="count" fill="#4350e5" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </ChartCard>
        </div>

        <div className="space-y-4">
          <ChartCard title="Bot Health" subtitle="Live service status">
            <ul className="space-y-2 text-sm">
              <ServiceRow label="Discord Bot" state={services?.bot_online ? "up" : "down"} />
              <ServiceRow label="Database" service={services?.database} />
              <ServiceRow label="Redis" service={services?.redis} />
              <ServiceRow label="Dashboard API" state={health.data !== null ? "up" : "down"} />
            </ul>
          </ChartCard>

          <div className="card p-5">
            <h2 className="font-semibold text-gray-900 dark:text-gray-100">Quick Actions</h2>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <Link className="btn-secondary justify-center" to="/dashboard/features">
                Manage features
              </Link>
              <Link className="btn-secondary justify-center" to="/dashboard/control">
                Bot control
              </Link>
              <Link className="btn-secondary justify-center" to="/dashboard/logs">
                Live logs
              </Link>
              <Link className="btn-secondary justify-center" to="/dashboard/analytics">
                Analytics
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

type ServiceState = "up" | "down" | "unconfigured";

function resolveState(service?: { up: boolean; configured: boolean } | boolean): ServiceState {
  if (typeof service === "boolean") return service ? "up" : "down";
  if (!service) return "down";
  if (service.up) return "up";
  if (!service.configured) return "unconfigured";
  return "down";
}

function ServiceRow({ label, state, service }: { label: string; state?: ServiceState; service?: { up: boolean; configured: boolean } }) {
  const s = state ?? resolveState(service);
  return (
    <li className="flex items-center justify-between">
      <span className="text-gray-600 dark:text-gray-300">{label}</span>
      <span
        className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${
          s === "up"
            ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-950 dark:text-emerald-400"
            : s === "unconfigured"
              ? "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400"
              : "bg-red-50 text-red-600 dark:bg-red-950 dark:text-red-400"
        }`}
      >
        <span className={`h-1.5 w-1.5 rounded-full ${
          s === "up" ? "bg-emerald-500" : s === "unconfigured" ? "bg-gray-400" : "bg-red-500"
        }`} />
        {s === "up" ? "Up" : s === "unconfigured" ? "Not configured" : "Down"}
      </span>
    </li>
  );
}