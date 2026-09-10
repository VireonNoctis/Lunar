# Lunar Dashboard Frontend

React + TypeScript + Vite dashboard for the Lunar Discord bot.

## Features

- **Overview** — active features, guilds, command usage, bot health
- **Features** — create/edit, global toggle, per-guild overrides
- **Guilds** — list guilds the bot is in, per-guild quick actions
- **Logs** — live WebSocket stream, query filters, CSV export
- **Analytics** — top commands and activity charts, JSON/CSV export
- **Control** — admin-only shutdown/restart/reload with confirmation + audit reason
- **Settings** — masked tokens, admin user management (owner-only)
- Dark/light theme, global keyboard shortcuts (`O/F/G/L/A/C/S`, `[` sidebar, `Ctrl+Shift+D` theme)

## Quick Start

```bash
# 1. Start the backend (from repo root)
pip install -r dashboard/backend/requirements.txt
cd dashboard/backend && python -m uvicorn main:app --reload --port 8000

# 2. Start the frontend (from this directory)
npm install
npm run dev
```

Open http://localhost:5173 and click **"Proceed as demo admin"**.

## How the API base works

The frontend uses **relative API paths** (same origin). In development the Vite
dev server proxies `/api`, `/ws`, `/auth` and `/health` to the backend at
`http://localhost:8000`, so the dashboard works from any host it's served on
(preview domains included) — no cross-origin `localhost` issues.

To point at a different backend, set `VITE_API_BASE` (e.g. a deployed API) or
`VITE_PROXY_TARGET` (the Vite proxy destination, default `http://localhost:8000`).

## Build

```bash
npm run build    # typechecks + outputs to dist/
npm run preview  # preview the static build
```

The Dockerfile builds the static site and serves it with nginx, which proxies
`/api`, `/ws` and `/auth` to the `dashboard-backend` service.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `VITE_API_BASE` | *(empty — same origin)* | Absolute backend URL override |
| `VITE_PROXY_TARGET` | `http://localhost:8000` | Vite dev proxy destination |
| `VITE_DEMO_ADMIN` | *(unused)* | Demo login is always available |

## Keyboard Shortcuts

- `O` Overview · `F` Features · `G` Guilds · `L` Logs
- `A` Analytics · `C` Control · `S` Settings
- `[` toggle sidebar · `Ctrl+Shift+D` toggle theme

## Project Structure

```
src/
  api/
    client.ts       — typed API client (Axios + WebSocket)
    batch.ts        — batch feature apply with per-feature fallback
  components/
    Layout.tsx      — shell with sidebar + header
    Nav.tsx         — sidebar navigation
    Header.tsx      — top bar (user, connection status)
    FeatureList.tsx — feature flags list
    FeatureToggle.tsx — individual feature toggle
    GuildRow.tsx    — guild list item
    LogTable.tsx    — log entries table (expandable details)
    ChartCard.tsx   — chart wrapper card
    ConfirmModal.tsx — confirmation dialog with audit reason
    Toast.tsx       — toast notification helper
    JsonDiff.tsx    — JSON diff viewer
  hooks/
    useAuth.tsx     — auth session (Discord OAuth + demo admin)
  pages/
    Login.tsx       — Discord OAuth + demo login
    Overview.tsx    — dashboard overview
    Features.tsx    — feature flag management + overrides modal
    Guilds.tsx      — guild list
    Logs.tsx        — live log viewer + CSV export
    Analytics.tsx   — usage charts + export
    Control.tsx     — admin controls + maintenance toggle
    Settings.tsx    — tokens + admin users
  styles/
    index.css       — Tailwind + theme tokens
  main.tsx          — React entry point
  App.tsx           — Router + protected routes
```