import { BrowserRouter, Route, Routes } from "react-router-dom";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { Login } from "./routes/Login";

function Dashboard() {
  return (
    <div className="p-8">
      Signed in.
      <form method="post" action="/api/auth/logout" className="mt-4">
        <button type="submit" className="rounded-lg bg-slate-900 text-white px-4 py-2 text-sm hover:bg-slate-800">
          Sign out
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
      </Routes>
    </BrowserRouter>
  );
}
