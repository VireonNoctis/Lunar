import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { Eye, EyeOff, Shield, UserPlus, Trash2 } from "lucide-react";
import { api } from "../api/client";
import { useAuth } from "../hooks/useAuth";

export default function Settings() {
  const { isOwner } = useAuth();
  const queryClient = useQueryClient();
  const [showTokens, setShowTokens] = useState<Record<string, boolean>>({});
  const [newAdminId, setNewAdminId] = useState("");
  const [newAdminName, setNewAdminName] = useState("");

  const admins = useQuery({
    queryKey: ["admins"],
    queryFn: api.fetchAdmins,
    enabled: isOwner,
  });

  const addAdmin = useMutation({
    mutationFn: () => api.addAdmin(newAdminId.trim(), newAdminName.trim()),
    onSuccess: () => {
      toast.success("Admin added");
      setNewAdminId("");
      setNewAdminName("");
      queryClient.invalidateQueries({ queryKey: ["admins"] });
    },
    onError: () => toast.error("Failed to add admin"),
  });

  const tokens = [
    { key: "DISCORD_TOKEN", label: "Discord Bot Token" },
    { key: "DATABASE_URL", label: "Database URL" },
    { key: "REDIS_URL", label: "Redis URL" },
    { key: "OAUTH_CLIENT_SECRET", label: "OAuth Client Secret" },
  ];

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="card p-5">
        <h2 className="font-semibold text-gray-900 dark:text-gray-100">Integration Tokens</h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Set these in the backend environment. Values are masked and never stored in the frontend.
        </p>
        <ul className="mt-4 space-y-2">
          {tokens.map((token) => (
            <li
              key={token.key}
              className="flex items-center justify-between rounded-lg border border-gray-200 px-3 py-2 dark:border-gray-700"
            >
              <div>
                <p className="text-sm font-medium text-gray-800 dark:text-gray-100">{token.label}</p>
                <p className="font-mono text-xs text-gray-400">{token.key}</p>
              </div>
              <button
                type="button"
                className="btn-secondary !px-2.5 !py-1.5"
                onClick={() => setShowTokens((prev) => ({ ...prev, [token.key]: !prev[token.key] }))}
                aria-label={`${showTokens[token.key] ? "Hide" : "Show"} ${token.label}`}
              >
                {showTokens[token.key] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="card p-5">
        <div className="flex items-center gap-2">
          <Shield className="h-5 w-5 text-lunar-500" />
          <h2 className="font-semibold text-gray-900 dark:text-gray-100">Admin Users</h2>
        </div>

        {!isOwner ? (
          <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">
            Only the bot owner can manage admin users.
          </p>
        ) : (
          <>
            <ul className="mt-4 space-y-2">
              {(admins.data ?? []).map((admin) => (
                <li
                  key={admin.id}
                  className="flex items-center justify-between rounded-lg border border-gray-200 px-3 py-2 dark:border-gray-700"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-gray-800 dark:text-gray-100">
                      {admin.username || "Unknown"}
                    </p>
                    <p className="font-mono text-xs text-gray-400">{admin.id}</p>
                  </div>
                  <span className="rounded-full bg-lunar-50 px-2 py-0.5 text-xs font-medium text-lunar-600 dark:bg-lunar-950 dark:text-lunar-400">
                    {admin.role}
                  </span>
                </li>
              ))}
              {admins.data?.length === 0 ? (
                <p className="text-sm text-gray-500">No admins configured.</p>
              ) : null}
            </ul>

            <div className="mt-4 flex flex-col gap-2 sm:flex-row">
              <input
                className="input sm:flex-1"
                placeholder="Discord user ID"
                value={newAdminId}
                onChange={(e) => setNewAdminId(e.target.value)}
                aria-label="Discord user ID"
              />
              <input
                className="input sm:flex-1"
                placeholder="Username (optional)"
                value={newAdminName}
                onChange={(e) => setNewAdminName(e.target.value)}
                aria-label="Username"
              />
              <button
                type="button"
                className="btn-primary"
                disabled={!newAdminId.trim()}
                onClick={() => addAdmin.mutate()}
              >
                <UserPlus className="h-4 w-4" />
                Add
              </button>
            </div>
          </>
        )}

        <div className="mt-6 border-t border-gray-200 pt-4 dark:border-gray-800">
          <button
            type="button"
            className="btn-secondary !text-red-600"
            onClick={() => toast("Local theme + demo data can be cleared via browser storage.", { icon: "🧹" })}
          >
            <Trash2 className="h-4 w-4" />
            Clear local data
          </button>
        </div>
      </div>
    </div>
  );
}