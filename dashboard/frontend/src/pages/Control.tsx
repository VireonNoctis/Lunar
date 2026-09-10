import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { Power, RefreshCw, RotateCw, ShieldAlert, Wrench } from "lucide-react";
import { api } from "../api/client";
import { useAuth } from "../hooks/useAuth";
import ConfirmModal from "../components/ConfirmModal";

type ControlAction = "shutdown" | "restart" | "reload";

export default function Control() {
  const { isAdmin, isOwner } = useAuth();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<ControlAction | null>(null);

  const health = useQuery({
    queryKey: ["bot-health"],
    queryFn: api.fetchBotHealth,
    refetchInterval: 5_000,
  });

  const control = useMutation({
    mutationFn: ({ action, reason }: { action: ControlAction; reason?: string }) =>
      api.sendControl(action, undefined, reason),
    onSuccess: () => {
      toast.success("Control action sent to bot");
      setPending(null);
      queryClient.invalidateQueries({ queryKey: ["bot-health"] });
    },
    onError: () => toast.error("Failed to send control action"),
  });

  if (!isAdmin) {
    return (
      <div className="card p-10 text-center">
        <ShieldAlert className="mx-auto h-10 w-10 text-amber-500" />
        <h2 className="mt-3 text-lg font-semibold text-gray-900 dark:text-gray-100">
          Admin access required
        </h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Only admins can control the bot. Sign in with an admin Discord account to continue.
        </p>
      </div>
    );
  }

  const bot = health.data?.bot;
  const maintenance = bot?.maintenance_mode ?? false;

  const toggleMaintenance = useMutation({
    mutationFn: (next: boolean) =>
      api.upsertFeature({
        name: "maintenance",
        description: maintenanceReason || "Global maintenance mode",
        enabled_globally: next,
        enabled_per_guild: {},
      }),
    onSuccess: () => {
      toast.success(`Maintenance ${maintenance ? "disabled" : "enabled"}`);
      queryClient.invalidateQueries({ queryKey: ["bot-health"] });
    },
    onError: () => toast.error("Failed to update maintenance mode"),
  });
  const [maintenanceReason, setMaintenanceReason] = useState("");

  return (
    <div className="space-y-6">
      <div className="card p-5">
        <h2 className="font-semibold text-gray-900 dark:text-gray-100">Bot Status</h2>
        <div className="mt-3 grid gap-3 text-sm sm:grid-cols-3">
          <StatusItem label="Uptime" value={bot?.uptime_seconds != null ? `${Math.floor(bot.uptime_seconds / 3600)}h ${Math.floor((bot.uptime_seconds % 3600) / 60)}m` : "—"} />
          <StatusItem label="Latency" value={bot?.latency_ms != null ? `${bot.latency_ms}ms` : "—"} />
          <StatusItem label="Loaded cogs" value={bot?.loaded_cogs?.length?.toString() ?? "—"} />
        </div>
      </div>

      <div className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-gray-900 dark:text-gray-100">Maintenance Mode</h2>
            <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
              Blocks all non-owner commands while enabled.
            </p>
          </div>
          <div className="flex items-center gap-3">
            {!maintenance ? (
              <input
                className="input sm:w-64"
                placeholder="Maintenance reason…"
                value={maintenanceReason}
                onChange={(e) => setMaintenanceReason(e.target.value)}
                aria-label="Maintenance reason"
              />
            ) : null}
            <button
              type="button"
              className={maintenance ? "btn-secondary" : "btn-primary"}
              onClick={() => toggleMaintenance.mutate(!maintenance)}
            >
              <Wrench className="h-4 w-4" />
              {maintenance ? "Disable maintenance" : "Enable maintenance"}
            </button>
          </div>
        </div>
      </div>

      <div className="card p-5">
        <h2 className="font-semibold text-gray-900 dark:text-gray-100">Danger Zone</h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          These actions are audited and rate-limited.
          {!isOwner ? " Owner access is required for shutdown and restart." : ""}
        </p>
        <div className="mt-4 flex flex-wrap gap-3">
          <button
            type="button"
            className="btn-secondary"
            disabled={!isOwner}
            onClick={() => setPending("reload")}
          >
            <RefreshCw className="h-4 w-4" />
            Reload cogs
          </button>
          <button
            type="button"
            className="btn-secondary"
            disabled={!isOwner}
            onClick={() => setPending("restart")}
          >
            <RotateCw className="h-4 w-4" />
            Restart bot
          </button>
          <button
            type="button"
            className="btn-danger"
            disabled={!isOwner}
            onClick={() => setPending("shutdown")}
          >
            <Power className="h-4 w-4" />
            Shutdown bot
          </button>
        </div>
      </div>

      <ConfirmModal
        open={pending !== null}
        title={
          pending === "shutdown"
            ? "Shutdown bot?"
            : pending === "restart"
              ? "Restart bot?"
              : "Reload all cogs?"
        }
        description={
          pending === "shutdown"
            ? "The bot will disconnect from Discord and stop."
            : pending === "restart"
              ? "The bot will disconnect, restart and re-sync its commands."
              : "All loaded cogs will be reloaded. A reason is recorded in the audit log."
        }
        confirmLabel={pending === "shutdown" ? "Shutdown" : pending === "restart" ? "Restart" : "Reload"}
        danger={pending === "shutdown"}
        requireReason
        onConfirm={(reason) => pending && control.mutate({ action: pending, reason })}
        onCancel={() => setPending(null)}
      />
    </div>
  );
}

function StatusItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-gray-200 p-3 dark:border-gray-700">
      <p className="text-xs font-medium uppercase tracking-wide text-gray-400">{label}</p>
      <p className="mt-1 font-semibold text-gray-900 dark:text-gray-100">{value}</p>
    </div>
  );
}