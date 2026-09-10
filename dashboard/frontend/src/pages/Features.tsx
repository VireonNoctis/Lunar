import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { Plus, X } from "lucide-react";
import { api, type Feature, type Guild } from "../api/client";
import { applyFeatureBatch } from "../api/batch";
import FeatureList from "../components/FeatureList";

export default function Features() {
  const queryClient = useQueryClient();
  const features = useQuery({ queryKey: ["features"], queryFn: api.fetchFeatures });
  const guilds = useQuery({ queryKey: ["guilds"], queryFn: api.fetchGuilds });

  const [editing, setEditing] = useState<Feature | null>(null);
  const [overridesFor, setOverridesFor] = useState<Feature | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [enabled, setEnabled] = useState(true);

  const upsert = useMutation({
    mutationFn: (feature: Partial<Feature> & { name: string }) => api.upsertFeature(feature),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["features"] });
      toast.success("Feature saved");
      setEditing(null);
    },
    onError: () => toast.error("Failed to save feature"),
  });

  const toggle = useMutation({
    mutationFn: ({ feature, enabled: value }: { feature: Feature; enabled: boolean }) =>
      api.upsertFeature({ ...feature, enabled_globally: value }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["features"] });
    },
    onError: () => toast.error("Failed to toggle feature"),
  });

  const applyOverrides = useMutation({
    mutationFn: (feature: Feature) => applyFeatureBatch([feature]),
    onSuccess: ({ applied }) => {
      queryClient.invalidateQueries({ queryKey: ["features"] });
      toast.success(`Saved overrides for ${applied} feature`);
      setOverridesFor(null);
    },
    onError: () => toast.error("Failed to save overrides"),
  });

  const openEdit = (feature: Feature) => {
    setEditing(feature);
    setName(feature.name);
    setDescription(feature.description);
    setEnabled(feature.enabled_globally);
  };

  const submit = () => {
    if (!name.trim()) return;
    upsert.mutate({
      name: name.trim(),
      description: description.trim(),
      enabled_globally: enabled,
      enabled_per_guild: editing?.enabled_per_guild ?? {},
    });
  };

  return (
    <div className="space-y-6">
      <div className="card p-5">
        <h2 className="font-semibold text-gray-900 dark:text-gray-100">
          {editing ? `Edit ${editing.name}` : "Create Feature"}
        </h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_2fr_auto_auto]">
          <input
            className="input"
            placeholder="name (e.g. tmusic)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-label="Feature name"
          />
          <input
            className="input"
            placeholder="Description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            aria-label="Feature description"
          />
          <label className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="h-4 w-4 rounded border-gray-300 text-lunar-600"
            />
            Enabled
          </label>
          <button type="button" className="btn-primary" onClick={submit}>
            <Plus className="h-4 w-4" />
            {editing ? "Save" : "Create"}
          </button>
        </div>
        {editing ? (
          <button
            type="button"
            className="mt-2 text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
            onClick={() => setEditing(null)}
          >
            Cancel editing
          </button>
        ) : null}
      </div>

      <FeatureList
        features={features.data ?? []}
        onToggle={(feature, value) => toggle.mutate({ feature, enabled: value })}
        onEdit={openEdit}
        onOpenOverrides={setOverridesFor}
      />

      {overridesFor ? (
        <OverridesModal
          feature={overridesFor}
          guilds={guilds.data ?? []}
          onClose={() => setOverridesFor(null)}
          onSave={(next) => applyOverrides.mutate(next)}
        />
      ) : null}
    </div>
  );
}

function OverridesModal({
  feature,
  guilds,
  onClose,
  onSave,
}: {
  feature: Feature;
  guilds: Guild[];
  onClose: () => void;
  onSave: (feature: Feature) => void;
}) {
  const [overrides, setOverrides] = useState<Record<string, boolean>>(
    feature.enabled_per_guild || {},
  );

  const cycle = (guildId: string) => {
    setOverrides((prev) => {
      const current = prev[guildId];
      const next = { ...prev };
      if (current === true) next[guildId] = false;
      else if (current === false) delete next[guildId];
      else next[guildId] = true;
      return next;
    });
  };

  const stateOf = (guildId: string): "global" | "on" | "off" => {
    const v = overrides[guildId];
    if (v === true) return "on";
    if (v === false) return "off";
    return "global";
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={`Per-guild overrides for ${feature.name}`}
    >
      <div className="card flex max-h-[80vh] w-full max-w-lg flex-col p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            Overrides — <span className="font-mono">{feature.name}</span>
          </h2>
          <button
            type="button"
            className="rounded-md p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
            onClick={onClose}
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Click a guild to cycle: <b>Global → On → Off</b>. Overrides beat the global toggle.
        </p>

        <div className="mt-4 flex-1 space-y-2 overflow-y-auto">
          {guilds.length === 0 ? (
            <p className="py-6 text-center text-sm text-gray-500">
              No guilds available. Start the backend to load guilds.
            </p>
          ) : (
            guilds.map((guild) => {
              const state = stateOf(guild.guild_id);
              return (
                <button
                  key={guild.guild_id}
                  type="button"
                  onClick={() => cycle(guild.guild_id)}
                  className="flex w-full items-center justify-between rounded-lg border border-gray-200 px-3 py-2 text-sm hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-800"
                >
                  <span className="truncate text-gray-800 dark:text-gray-100">{guild.name}</span>
                  <span
                    className={`ml-3 shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${
                      state === "on"
                        ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-950 dark:text-emerald-400"
                        : state === "off"
                          ? "bg-red-50 text-red-600 dark:bg-red-950 dark:text-red-400"
                          : "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400"
                    }`}
                  >
                    {state === "on" ? "On" : state === "off" ? "Off" : "Global"}
                  </span>
                </button>
              );
            })
          )}
        </div>

        <div className="mt-5 flex justify-end gap-3">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={() => onSave({ ...feature, enabled_per_guild: overrides })}
          >
            Save overrides
          </button>
        </div>
      </div>
    </div>
  );
}