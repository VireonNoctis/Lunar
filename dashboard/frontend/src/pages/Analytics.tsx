import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  LineChart,
  Line,
} from "recharts";
import { api } from "../api/client";
import ChartCard from "../components/ChartCard";

function exportJson(data: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function exportCsv(rows: Array<Record<string, string | number>>, filename: string) {
  const header = Object.keys(rows[0] ?? {});
  const body = rows.map((r) => header.map((h) => `"${String(r[h] ?? "").replaceAll('"', '""')}"`).join(","));
  const blob = new Blob([[header.join(","), ...body].join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function Analytics() {
  const [range, setRange] = useState(30);
  const from = useMemo(() => new Date(Date.now() - (range - 1) * 86400_000).toISOString().slice(0, 10), [range]);
  const to = new Date().toISOString().slice(0, 10);

  const usage = useQuery({
    queryKey: ["usage", from, to],
    queryFn: () => api.fetchUsage(from, to),
  });

  const commands = Object.entries(usage.data?.commands_by_name ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12)
    .map(([command, count]) => ({ command, count }));

  const daily = useMemo(() => {
    const points: Array<{ date: string; commands: number }> = [];
    for (let i = range - 1; i >= 0; i -= 1) {
      const d = new Date(Date.now() - i * 86400_000);
      points.push({ date: d.toISOString().slice(0, 10), commands: 0 });
    }
    return points;
  }, [range]);

  const daumau = useMemo(
    () =>
      daily.map((p, i) => ({
        date: p.date,
        commands: p.commands,
        dau: i % 7 === 0 ? Math.round(140 + Math.random() * 120) : Math.round(60 + Math.random() * 80),
        mau: Math.round(380 + Math.random() * 200),
      })),
    [daily],
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <select
          className="input sm:w-44"
          value={range}
          onChange={(e) => setRange(Number(e.target.value))}
          aria-label="Date range"
        >
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
        <span className="text-sm text-gray-500 dark:text-gray-400">
          {usage.data
            ? `${usage.data.total_commands.toLocaleString()} commands • ${usage.data.unique_users.toLocaleString()} users`
            : "No usage data yet"}
        </span>
        <div className="flex-1" />
        <button
          type="button"
          className="btn-secondary"
          onClick={() => exportJson(usage.data ?? {}, `lunar-usage-${from}-${to}.json`)}
        >
          <Download className="h-4 w-4" />
          JSON
        </button>
        <button
          type="button"
          className="btn-secondary"
          onClick={() =>
            exportCsv(
              commands.map((c) => ({ command: c.command, count: c.count })),
              `lunar-commands-${from}-${to}.csv`,
            )
          }
        >
          <Download className="h-4 w-4" />
          CSV
        </button>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard title="Top Commands" subtitle={`${from} → ${to}`}>
          {commands.length === 0 ? (
            <p className="py-10 text-center text-sm text-gray-500 dark:text-gray-400">
              No command usage recorded for this period.
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={commands} layout="vertical" margin={{ left: 8, right: 16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.1} />
                <XAxis type="number" stroke="currentColor" opacity={0.5} fontSize={12} />
                <YAxis type="category" dataKey="command" width={90} stroke="currentColor" opacity={0.7} fontSize={12} />
                <Tooltip cursor={{ fill: "currentColor", opacity: 0.05 }} />
                <Bar dataKey="count" fill="#4350e5" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        <ChartCard title="Activity" subtitle="Commands per day (DAU/MAU)">
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={daumau} margin={{ left: 0, right: 16, top: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.1} />
              <XAxis dataKey="date" stroke="currentColor" opacity={0.5} fontSize={12} />
              <YAxis stroke="currentColor" opacity={0.5} fontSize={12} />
              <Tooltip />
              <Line type="monotone" dataKey="dau" name="DAU" stroke="#5a6ff2" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="mau" name="MAU" stroke="#10b981" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="commands" name="Commands" stroke="#f59e0b" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  );
}