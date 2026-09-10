import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  ToggleLeft,
  Server,
  ScrollText,
  BarChart3,
  Power,
  Settings as SettingsIcon,
} from "lucide-react";

interface NavItem {
  to: string;
  label: string;
  icon: typeof LayoutDashboard;
  key: string;
}

const items: NavItem[] = [
  { to: "/dashboard", label: "Overview", icon: LayoutDashboard, key: "o" },
  { to: "/dashboard/features", label: "Features", icon: ToggleLeft, key: "f" },
  { to: "/dashboard/guilds", label: "Guilds", icon: Server, key: "g" },
  { to: "/dashboard/logs", label: "Logs", icon: ScrollText, key: "l" },
  { to: "/dashboard/analytics", label: "Analytics", icon: BarChart3, key: "a" },
  { to: "/dashboard/control", label: "Control", icon: Power, key: "c" },
  { to: "/dashboard/settings", label: "Settings", icon: SettingsIcon, key: "s" },
];

export default function Nav({
  collapsed,
  onNavigate,
}: {
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  return (
    <nav className="flex-1 space-y-1 overflow-y-auto px-2 py-4" aria-label="Main navigation">
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          onClick={onNavigate}
          title={`${item.label} (${item.key.toUpperCase()})`}
          className={({ isActive }) =>
            `group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              isActive
                ? "bg-lunar-600 text-white"
                : "text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-gray-100"
            }`
          }
        >
          <item.icon className="h-5 w-5 shrink-0" aria-hidden="true" />
          {!collapsed ? (
            <>
              <span className="flex-1 truncate">{item.label}</span>
              <kbd className="hidden rounded border border-current/20 px-1 text-[10px] uppercase opacity-50 lg:inline">
                {item.key}
              </kbd>
            </>
          ) : null}
        </NavLink>
      ))}
    </nav>
  );
}