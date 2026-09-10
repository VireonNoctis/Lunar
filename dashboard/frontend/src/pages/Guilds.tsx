import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { Search } from "lucide-react";
import { api } from "../api/client";
import GuildRow from "../components/GuildRow";

export default function Guilds() {
  const guilds = useQuery({ queryKey: ["guilds"], queryFn: api.fetchGuilds, refetchInterval: 60_000 });
  const [query, setQuery] = useState("");

  const filtered = (guilds.data ?? []).filter(
    (g) => !query.trim() || g.name.toLowerCase().includes(query.trim().toLowerCase()),
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="search"
            className="input pl-9"
            placeholder="Search guilds…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search guilds"
          />
        </div>
        <span className="text-sm text-gray-500 dark:text-gray-400">
          {guilds.data ? `${guilds.data.length} guilds` : "Loading…"}
        </span>
      </div>

      <div className="space-y-2">
        {filtered.length === 0 ? (
          <div className="card p-8 text-center text-sm text-gray-500 dark:text-gray-400">
            {guilds.isLoading
              ? "Loading guilds…"
              : guilds.data?.length === 0
                ? "The bot is not in any guilds yet, or the backend is unreachable."
                : "No guilds match your search."}
          </div>
        ) : (
          filtered.map((guild) => (
            <GuildRow
              key={guild.guild_id}
              guild={guild}
              onOpenOverrides={(guildId) => {
                toast(`Feature overrides for ${guildId} open on the Features page`, {
                  icon: "🌙",
                });
              }}
            />
          ))
        )}
      </div>
    </div>
  );
}