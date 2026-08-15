import { Login } from "./routes/Login";
import { NotFound } from "./routes/NotFound";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { BrowserRouter, Route, Routes } from "react-router-dom";

function Dashboard() {
  return (
    <div className="p-8">
      Signed in.
      <form method="post" action="/api/auth/logout" className="mt-4">
        <button
          type="submit"
          className="rounded-lg bg-secondary text-secondary-foreground px-4 py-2 text-sm hover:bg-secondary-hover"
        >
          Sign Out
        </button>
      </form>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Dashboard />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  );
}
