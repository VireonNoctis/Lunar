import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { ShieldCheck, UserRound } from "lucide-react";
import { useAuth } from "../hooks/useAuth";

export default function Login() {
  const { user, loginDemo, loginDiscord } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const returnTo = params.get("returnTo") || "/dashboard";

  if (user) return <Navigate to={returnTo} replace />;

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-lunar-950 via-gray-950 to-gray-900 p-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <span className="text-5xl" aria-hidden="true">🌙</span>
          <h1 className="mt-3 text-3xl font-bold tracking-tight text-white">Lunar Dashboard</h1>
          <p className="mt-2 text-sm text-gray-400">
            Manage Lunar's features, guilds, logs and infrastructure.
          </p>
        </div>

        <div className="card border-gray-800 bg-gray-900/80 p-6">
          <button
            type="button"
            className="btn-primary w-full !bg-[#5865F2] hover:!bg-[#4752c4] !py-3"
            onClick={loginDiscord}
          >
            <ShieldCheck className="h-5 w-5" />
            Sign in with Discord
          </button>

          <div className="my-4 flex items-center gap-3 text-xs uppercase tracking-wide text-gray-500">
            <span className="h-px flex-1 bg-gray-700" />
            or
            <span className="h-px flex-1 bg-gray-700" />
          </div>

          <button
            type="button"
            className="btn-secondary w-full !py-3"
            onClick={() => {
              loginDemo();
              navigate(returnTo);
            }}
          >
            <UserRound className="h-5 w-5" />
            Proceed as demo admin
          </button>

          <p className="mt-4 text-center text-xs text-gray-500">
            Demo mode works without Discord OAuth and is meant for local testing.
          </p>
        </div>
      </div>
    </div>
  );
}