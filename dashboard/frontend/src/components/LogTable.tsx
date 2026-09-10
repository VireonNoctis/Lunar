import { useState } from "react";
import { ChevronDown, Copy } from "lucide-react";
import type { LogEntry } from "../api/client";

const LEVEL_STYLES: Record<string, string> = {
  ERROR: "bg-red-50 text-red-600 dark:bg-red-950 dark:text-red-400",
  WARNING: "bg-amber-50 text-amber-600 dark:bg-amber-950 dark:text-amber-400",
  INFO: "bg-lunar-50 text-lunar-600 dark:bg-lunar-950 dark:text-lunar-400",
  DEBUG: "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400",
};

function pretty(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export default function LogTable({ logs }: { logs: LogEntry[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  if (logs.length === 0) {
    return (
      <div className="card p-8 text-center text-sm text-gray-500 dark:text-gray-400">
        No log entries. Start the backend or trigger an action to see entries appear here.
      </div>
    );
  }

  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead className="border-b border-gray-200 bg-gray-50 text-xs uppercase tracking-wide text-gray-500 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400">
            <tr>
              <th className="px-4 py-3 font-medium">Level</th>
              <th className="px-4 py-3 font-medium">Action</th>
              <th className="px-4 py-3 font-medium">Target</th>
              <th className="px-4 py-3 font-medium">Actor</th>
              <th className="px-4 py-3 font-medium">Timestamp</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {logs.map((log, i) => {
              const key = `${log.timestamp}-${i}`;
              const open = expanded.has(key);
              return (
                <LogRow
                  key={key}
                  log={log}
                  open={open}
                  onToggle={() => toggle(key)}
                />
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function LogRow({
  log,
  open,
  onToggle,
}: {
  log: LogEntry;
  open: boolean;
  onToggle: () => void;
}) {
  const hasDetails = log.details !== undefined && log.details !== null && log.details !== "";
  const level = (log.level || "INFO").toUpperCase();

  return (
    <>
      <tr
        className="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/50"
        onClick={onToggle}
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggle();
          }
        }}
      >
        <td className="px-4 py-3">
          <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${LEVEL_STYLES[level] ?? LEVEL_STYLES.INFO}`}>
            {level}
          </span>
        </td>
        <td className="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">{log.action}</td>
        <td className="px-4 py-3 text-gray-600 dark:text-gray-300">{log.target || "—"}</td>
        <td className="px-4 py-3 font-mono text-xs text-gray-500 dark:text-gray-400">
          {log.actor_id || "system"}
        </td>
        <td className="px-4 py-3 text-gray-500 dark:text-gray-400">
          {new Date(log.timestamp).toLocaleString()}
        </td>
        <td className="px-4 py-3 text-right">
          {hasDetails ? (
            <ChevronDown
              className={`inline h-4 w-4 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`}
            />
          ) : null}
        </td>
      </tr>
      {open && hasDetails ? (
        <tr>
          <td colSpan={6} className="bg-gray-50 px-4 py-3 dark:bg-gray-900/60">
            <div className="relative">
              <pre className="overflow-x-auto rounded-lg bg-gray-900 p-4 text-xs leading-relaxed text-gray-100 dark:bg-black/40">
                {pretty(log.details)}
              </pre>
              <button
                type="button"
                className="absolute right-2 top-2 rounded-md bg-white/10 p-1.5 text-gray-200 hover:bg-white/20"
                onClick={(e) => {
                  e.stopPropagation();
                  void navigator.clipboard.writeText(pretty(log.details));
                }}
                aria-label="Copy details"
              >
                <Copy className="h-3.5 w-3.5" />
              </button>
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}