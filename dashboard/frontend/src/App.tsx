import { Route, Routes, Navigate } from "react-router-dom";
import { RequireAuth } from "./hooks/useAuth";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import Features from "./pages/Features";
import Guilds from "./pages/Guilds";
import Logs from "./pages/Logs";
import Analytics from "./pages/Analytics";
import Control from "./pages/Control";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="/auth" element={<Login />} />
      <Route
        path="/dashboard"
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Overview />} />
        <Route path="features" element={<Features />} />
        <Route path="guilds" element={<Guilds />} />
        <Route path="logs" element={<Logs />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="control" element={<Control />} />
        <Route path="settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}