import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, Radio } from "lucide-react";
import { api, connectLogStream, type LogEntry } from "../api/client";
import LogTable from "../components/LogTable";

function toCsv(logs: LogEntry[]): string {
  const header = ["timestamp", "level", "action", "target", "actor_id", "details"];
  const rows = logs.map((l) =>
    [
      l.timestamp,
      l.level ?? "INFO",
      l.action,
      l.target ?? "",
      l.actor_id ?? "",
      JSON.stringify(l.details ?? {}),
    ]
      .map((v) => `"${String(v).replaceAll('"', '""')}"`)
      .join(","),
  );
  return [header.join(","), ...rows].join("\n");
}

export default function Logs() {
  const [live, setLive] = useState(true);
  const [connected, setConnected] = useState(false);
  const [level, setLevel] = useState("");
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const limit = 100;

  const query = useQuery({
    queryKey: ["logs", level, limit],
    queryFn: () => api.fetchLogs({ limit, level: level || undefined }),
    refetchInterval: live ? 10_000 : undefined,
    enabled: !live || logs.length === 0,
  });

  const latest = useRef<LogEntry[]>([]);

  useEffect(() => {
    latest.current = logs;
  }, [logs]);

  useEffect(() => {
    if (!live) return undefined;
    const stop = connectLogStream(
      (entry) => {
        setLogs((prev) => [entry, ...prev].slice(0, 200));
      },
      setConnected,
    );
    return stop;
  }, [live]);

  const displayed = live ? (logs.length > 0 ? logs : query.data ?? []) : (query.data ?? []);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className={live ? "btn-primary" : "btn-secondary"}
          onClick={() => setLive((v) => !v)}
        >
          <Radio className="h-4 w-4" />
          Live {connected ? "● Connected" : "○ Off"}
        </button>

        <select
          className="input w-full sm:w-40"
          value={level}
          onChange={(e) => setLevel(e.target.value)}
          aria-label="Filter by level"
        >
          <option value="">All levels</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
          <option value="DEBUG">DEBUG</option>
        </select>

        <div className="flex-1" />

        <button
          type="button"
          className="btn-secondary"
          onClick={() => {
            const blob = new Blob([toCsv(displayed)], { type: "text/csv" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `lunar-logs-${new Date().toISOString().slice(0, 10)}.csv`;
            a.click();
            URL.revokeObjectURL(url);
          }}
        >
          <Download className="h-4 w-4" />
          Export CSV
        </button>
      </div>

      <LogTable logs={displayed} />
    </div>
  );
}