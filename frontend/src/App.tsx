import { Routes, Route, Navigate } from "react-router-dom";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import BotList from "./pages/BotList";
import CreateBot from "./pages/CreateBot";
import BotDetail from "./pages/BotDetail";
import KeyList from "./pages/KeyList";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { AdminLayout } from "./components/AdminLayout";

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />

      <Route element={<ProtectedRoute />}>
        <Route element={<AdminLayout />}>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/bots" element={<BotList />} />
          <Route path="/bots/new" element={<CreateBot />} />
          <Route path="/bots/:id" element={<BotDetail />} />
          <Route path="/keys" element={<KeyList />} />
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
