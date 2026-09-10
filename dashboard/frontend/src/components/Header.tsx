import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { LogOut, Menu, Wifi, WifiOff } from "lucide-react";
import { useAuth } from "../hooks/useAuth";
import { api } from "../api/client";

const TITLES: Record<string, string> = {
  "/dashboard": "Overview",
  "/dashboard/features": "Features",
  "/dashboard/guilds": "Guilds",
  "/dashboard/logs": "Logs",
  "/dashboard/analytics": "Analytics",
  "/dashboard/control": "Control",
  "/dashboard/settings": "Settings",
};

export default function Header({ onOpenSidebar }: { onOpenSidebar: () => void }) {
  const { user, logout } = useAuth();
  const location = useLocation();
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    let active = true;
    const check = async () => {
      const health = await api.fetchBotHealth();
      if (active) setOnline(health !== null);
    };
    check();
    const id = window.setInterval(check, 15_000);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, []);

  const avatarUrl = user?.avatar
    ? `https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png?size=64`
    : null;

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-3 border-b border-gray-200 bg-white px-4 dark:border-gray-800 dark:bg-gray-900 sm:px-6">
      <div className="flex min-w-0 items-center gap-2">
        <button
          type="button"
          className="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-900 dark:hover:bg-gray-800 dark:hover:text-gray-100 lg:hidden"
          onClick={onOpenSidebar}
          aria-label="Open navigation"
        >
          <Menu className="h-5 w-5" />
        </button>
        <h1 className="truncate text-base font-semibold text-gray-900 dark:text-gray-100 sm:text-lg">
          {TITLES[location.pathname] ?? "Lunar"}
        </h1>
      </div>

      <div className="flex min-w-0 items-center gap-2 sm:gap-4">
        <span
          className={`hidden items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium sm:inline-flex ${
            online === false
              ? "bg-red-50 text-red-600 dark:bg-red-950 dark:text-red-400"
              : "bg-emerald-50 text-emerald-600 dark:bg-emerald-950 dark:text-emerald-400"
          }`}
          title="Backend connection status"
        >
          {online === false ? (
            <>
              <WifiOff className="h-3.5 w-3.5" /> Offline
            </>
          ) : (
            <>
              <Wifi className="h-3.5 w-3.5" /> Connected
            </>
          )}
        </span>

        {user ? (
          <div className="flex min-w-0 items-center gap-2">
            {avatarUrl ? (
              <img
                src={avatarUrl}
                alt=""
                className="h-8 w-8 shrink-0 rounded-full"
                referrerPolicy="no-referrer"
              />
            ) : (
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-lunar-600 text-sm font-semibold text-white">
                {user.username.charAt(0).toUpperCase()}
              </span>
            )}
            <span className="hidden max-w-[120px] truncate text-sm font-medium text-gray-700 dark:text-gray-200 md:block">
              {user.username}
            </span>
            <button
              type="button"
              className="btn-secondary !px-2 !py-1.5 sm:!px-2.5"
              onClick={logout}
              aria-label="Log out"
              title="Log out"
            >
              <LogOut className="h-4 w-4" />
              <span className="hidden sm:inline">Log out</span>
            </button>
          </div>
        ) : null}
      </div>
    </header>
  );
}