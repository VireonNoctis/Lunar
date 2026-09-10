import { useEffect, useState } from "react";
import { Outlet, useNavigate } from "react-router-dom";
import { Moon, PanelLeft, Sun, X } from "lucide-react";
import Nav from "./Nav";
import Header from "./Header";

export default function Layout() {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const navigate = useNavigate();

  useEffect(() => {
    if (dark) document.documentElement.classList.add("dark");
    else document.documentElement.classList.remove("dark");
    localStorage.setItem("lunar_theme", dark ? "dark" : "light");
  }, [dark]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const map: Record<string, string> = {
        o: "/dashboard",
        f: "/dashboard/features",
        g: "/dashboard/guilds",
        l: "/dashboard/logs",
        a: "/dashboard/analytics",
        c: "/dashboard/control",
        s: "/dashboard/settings",
        "[": "sidebar",
      };
      const route = map[e.key.toLowerCase()];
      if (route === "sidebar") {
        if (window.innerWidth < 1024) setMobileOpen((v) => !v);
        else setCollapsed((c) => !c);
      } else if (route) {
        setMobileOpen(false);
        navigate(route);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [navigate]);

  useEffect(() => {
    const ctrlShift = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "d") {
        e.preventDefault();
        setDark((d) => !d);
      }
    };
    window.addEventListener("keydown", ctrlShift);
    return () => window.removeEventListener("keydown", ctrlShift);
  }, []);

  // Lock body scroll while the mobile drawer is open.
  useEffect(() => {
    document.body.style.overflow = mobileOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [mobileOpen]);

  const closeMobile = () => setMobileOpen(false);

  return (
    <div className="flex min-h-screen bg-gray-50 dark:bg-gray-950">
      {/* Backdrop for the mobile drawer */}
      {mobileOpen ? (
        <div
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
          onClick={closeMobile}
          aria-hidden="true"
        />
      ) : null}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-64 shrink-0 flex-col border-r border-gray-200 bg-white transition-transform duration-200 dark:border-gray-800 dark:bg-gray-900 lg:static lg:z-auto lg:translate-x-0 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        } ${collapsed ? "lg:w-16" : "lg:w-60"}`}
        aria-label="Sidebar"
      >
        <div className="flex h-16 items-center justify-between gap-3 border-b border-gray-200 px-4 dark:border-gray-800">
          <div className="flex min-w-0 items-center gap-3">
            <span className="text-2xl" aria-hidden="true">🌙</span>
            {!collapsed ? (
              <span className="truncate text-lg font-bold tracking-tight text-gray-900 dark:text-gray-100">
                Lunar
              </span>
            ) : null}
          </div>
          <button
            type="button"
            className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-800 dark:hover:text-gray-200 lg:hidden"
            onClick={closeMobile}
            aria-label="Close navigation"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <Nav collapsed={collapsed} onNavigate={closeMobile} />

        <button
          type="button"
          className="m-3 hidden items-center justify-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800 lg:flex"
          onClick={() => setCollapsed((c) => !c)}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title="Toggle sidebar ([)"
        >
          <PanelLeft className="h-4 w-4" />
          {!collapsed ? <span>Collapse</span> : null}
        </button>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <Header onOpenSidebar={() => setMobileOpen(true)} />
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
          <Outlet />
        </main>
        <footer className="flex items-center justify-between border-t border-gray-200 px-4 py-3 text-xs text-gray-400 dark:border-gray-800 dark:text-gray-500 sm:px-6">
          <span>Lunar Dashboard v1.0</span>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 hover:bg-gray-100 dark:hover:bg-gray-800"
            onClick={() => setDark((d) => !d)}
            aria-label="Toggle theme"
            title="Toggle theme (Ctrl+Shift+D)"
          >
            {dark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
            <span>{dark ? "Light" : "Dark"}</span>
          </button>
        </footer>
      </div>
    </div>
  );
}