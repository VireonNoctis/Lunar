import { useState } from "react";

function serialize(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

interface JsonDiffProps {
  oldValue: unknown;
  newValue: unknown;
}

export default function JsonDiff({ oldValue, newValue }: JsonDiffProps) {
  const [mode, setMode] = useState<"split" | "unified">("split");

  const oldLines = serialize(oldValue).split("\n");
  const newLines = serialize(newValue).split("\n");

  const renderSide = (lines: string[], side: "old" | "new") => (
    <pre
      className={`flex-1 overflow-x-auto rounded-lg bg-gray-50 p-4 text-xs leading-relaxed dark:bg-gray-900 ${
        side === "old" ? "text-gray-600 dark:text-gray-400" : "text-gray-900 dark:text-gray-100"
      }`}
    >
      {lines.join("\n")}
    </pre>
  );

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-gray-400">JSON diff</span>
        <div className="flex gap-1">
          {(["split", "unified"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`rounded-md px-2 py-1 text-xs font-medium ${
                mode === m
                  ? "bg-lunar-600 text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300"
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      {mode === "split" ? (
        <div className="flex gap-2">
          <div className="flex-1">
            <p className="mb-1 text-xs text-red-500">Before</p>
            {renderSide(oldLines, "old")}
          </div>
          <div className="flex-1">
            <p className="mb-1 text-xs text-emerald-500">After</p>
            {renderSide(newLines, "new")}
          </div>
        </div>
      ) : (
        <pre className="overflow-x-auto rounded-lg bg-gray-900 p-4 text-xs leading-relaxed text-gray-100">
          {oldLines.map((line, i) => (
            <div key={`old-${i}`} className="text-red-400">
              - {line}
            </div>
          ))}
          {newLines.map((line, i) => (
            <div key={`new-${i}`} className="text-emerald-400">
              + {line}
            </div>
          ))}
        </pre>
      )}
    </div>
  );
}