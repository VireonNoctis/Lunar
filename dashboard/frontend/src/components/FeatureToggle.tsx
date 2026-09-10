import type { ReactNode } from "react";
import type { Feature } from "../api/client";

interface FeatureToggleProps {
  feature: Feature;
  onToggle: (feature: Feature, enabled: boolean) => void;
  actions?: ReactNode;
}

export default function FeatureToggle({ feature, onToggle, actions }: FeatureToggleProps) {
  const overrideCount = Object.keys(feature.enabled_per_guild || {}).length;

  return (
    <div className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <h3 className="font-mono text-sm font-semibold text-gray-900 dark:text-gray-100">
            {feature.name}
          </h3>
          {feature.enabled_globally ? (
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-600 dark:bg-emerald-950 dark:text-emerald-400">
              Global
            </span>
          ) : (
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500 dark:bg-gray-800 dark:text-gray-400">
              Off
            </span>
          )}
          {overrideCount > 0 ? (
            <span className="rounded-full bg-lunar-50 px-2 py-0.5 text-xs font-medium text-lunar-600 dark:bg-lunar-950 dark:text-lunar-400">
              {overrideCount} override{overrideCount === 1 ? "" : "s"}
            </span>
          ) : null}
        </div>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">{feature.description}</p>
        {feature.updated_at ? (
          <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
            Updated {new Date(feature.updated_at).toLocaleString()}
            {feature.updated_by ? ` by ${feature.updated_by}` : ""}
          </p>
        ) : null}
      </div>

      <div className="flex items-center gap-3">
        {actions}
        <button
          type="button"
          role="switch"
          aria-checked={feature.enabled_globally}
          aria-label={`Toggle ${feature.name}`}
          className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
            feature.enabled_globally ? "bg-lunar-600" : "bg-gray-300 dark:bg-gray-700"
          }`}
          onClick={() => onToggle(feature, !feature.enabled_globally)}
        >
          <span
            className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
              feature.enabled_globally ? "translate-x-[22px]" : "translate-x-0.5"
            }`}
          />
        </button>
      </div>
    </div>
  );
}