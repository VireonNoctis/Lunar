import { ExternalLink, Settings2 } from "lucide-react";
import type { Guild } from "../api/client";

interface GuildRowProps {
  guild: Guild;
  onOpenOverrides: (guildId: string, guildName: string) => void;
}

export default function GuildRow({ guild, onOpenOverrides }: GuildRowProps) {
  const iconUrl = guild.icon
    ? `https://cdn.discordapp.com/icons/${guild.guild_id}/${guild.icon}.png?size=128`
    : null;

  return (
    <div className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:gap-4">
      <div className="flex items-center gap-3 sm:gap-4">
        {iconUrl ? (
          <img
            src={iconUrl}
            alt=""
            className="h-10 w-10 shrink-0 rounded-full sm:h-12 sm:w-12"
            referrerPolicy="no-referrer"
          />
        ) : (
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-lunar-600 text-base font-bold text-white sm:h-12 sm:w-12 sm:text-lg">
            {guild.name.charAt(0).toUpperCase()}
          </span>
        )}

        <div className="min-w-0">
          <h3 className="truncate font-semibold text-gray-900 dark:text-gray-100">{guild.name}</h3>
          <p className="truncate text-sm text-gray-500 dark:text-gray-400">
            {guild.member_count != null ? `${guild.member_count.toLocaleString()} members` : "Member count unavailable"}
            {guild.joined_at ? ` • joined ${new Date(guild.joined_at).toLocaleDateString()}` : ""}
          </p>
        </div>
      </div>

      <div className="flex items-center justify-end gap-2 sm:ml-auto">
        <button
          type="button"
          className="btn-secondary !px-2.5 !py-1.5"
          onClick={() => onOpenOverrides(guild.guild_id, guild.name)}
          title="Open feature overrides for this guild"
          aria-label={`Feature overrides for ${guild.name}`}
        >
          <Settings2 className="h-4 w-4" />
        </button>
        <a
          className="btn-secondary !px-2.5 !py-1.5"
          href={`https://discord.com/channels/${guild.guild_id}`}
          target="_blank"
          rel="noreferrer"
          title="Open guild in Discord"
          aria-label={`Open ${guild.name} in Discord`}
        >
          <ExternalLink className="h-4 w-4" />
        </a>
      </div>
    </div>
  );
}