import { useMemo, useState } from "react";
import { Pencil, Search, Server } from "lucide-react";
import type { Feature } from "../api/client";
import FeatureToggle from "./FeatureToggle";

interface FeatureListProps {
  features: Feature[];
  onToggle: (feature: Feature, enabled: boolean) => void;
  onEdit: (feature: Feature) => void;
  onOpenOverrides: (feature: Feature) => void;
}

type SortKey = "name" | "enabled_globally";

export default function FeatureList({ features, onToggle, onEdit, onOpenOverrides }: FeatureListProps) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("name");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = features.filter(
      (f) => !q || f.name.toLowerCase().includes(q) || f.description.toLowerCase().includes(q),
    );
    return [...list].sort((a, b) => {
      if (sort === "name") return a.name.localeCompare(b.name);
      return Number(b.enabled_globally) - Number(a.enabled_globally);
    });
  }, [features, query, sort]);

  return (
    <div>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="search"
            className="input pl-9"
            placeholder="Search features…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search features"
          />
        </div>
        <select
          className="input sm:w-48"
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          aria-label="Sort features"
        >
          <option value="name">Sort by name</option>
          <option value="enabled_globally">Enabled first</option>
        </select>
      </div>

      <div className="space-y-2">
        {filtered.length === 0 ? (
          <div className="card p-8 text-center text-sm text-gray-500 dark:text-gray-400">
            {features.length === 0
              ? "No features yet. Create one with the form above, or start the backend so data loads."
              : "No features match your search."}
          </div>
        ) : (
          filtered.map((feature) => (
            <FeatureToggle
              key={feature.name}
              feature={feature}
              onToggle={onToggle}
              actions={
                <>
                  <button
                    type="button"
                    className="btn-secondary !px-2.5 !py-1.5"
                    onClick={() => onOpenOverrides(feature)}
                    title="Per-guild overrides"
                    aria-label={`Per-guild overrides for ${feature.name}`}
                  >
                    <Server className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    className="btn-secondary !px-2.5 !py-1.5"
                    onClick={() => onEdit(feature)}
                    title="Edit feature"
                    aria-label={`Edit ${feature.name}`}
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                </>
              }
            />
          ))
        )}
      </div>
    </div>
  );
}