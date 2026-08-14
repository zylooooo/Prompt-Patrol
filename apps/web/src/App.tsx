import { Login } from "./routes/Login";
import { NotFound } from "./routes/NotFound";
import AppShell from "./components/AppShell";
import PageHeader from "./components/PageHeader";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

function Placeholder() {
  return (
    <PageHeader
      title="Check answers"
      subtitle="Pages land in the next step of the port."
    />
  );
}

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
          <Route path="check" element={<Placeholder />} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  );
}
