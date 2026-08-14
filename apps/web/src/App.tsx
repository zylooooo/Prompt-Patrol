import { Login } from "./routes/Login";
import CheckPage from "./pages/CheckPage";
import UsersPage from "./pages/UsersPage";
import { NotFound } from "./routes/NotFound";
import AppShell from "./components/AppShell";
import HistoryPage from "./pages/HistoryPage";
import HistoryDetailPage from "./pages/HistoryDetailPage";
import { ProtectedRoute } from "./components/ProtectedRoute";
import TeachingAssistantsPage from "./pages/TeachingAssistantsPage";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          element={
            <ProtectedRoute>
              <AppShell />
            </ProtectedRoute>
          }
        >
          <Route index element={<Navigate to="/check" replace />} />
          <Route path="check" element={<CheckPage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="history/:id" element={<HistoryDetailPage />} />
          <Route
            path="teaching-assistants"
            element={
              <ProtectedRoute minRole="instructor">
                <TeachingAssistantsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="users"
            element={
              <ProtectedRoute minRole="root_admin">
                <UsersPage />
              </ProtectedRoute>
            }
          />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  );
}
