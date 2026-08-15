import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import { AuthProvider, RequireAdmin, RequireAuth, RequireInstructor } from './lib/auth'
import { ToastProvider } from './lib/toast'
import TeachingAssistantsPage from './pages/TeachingAssistantsPage'
import AppShell from './components/AppShell'
import LoginPage from './pages/LoginPage'
import CheckPage from './pages/CheckPage'
import HistoryPage from './pages/HistoryPage'
import HistoryDetailPage from './pages/HistoryDetailPage'
import UsersPage from './pages/UsersPage'

const queryClient = new QueryClient()

const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/check" replace /> },
      { path: 'check', element: <CheckPage /> },
      { path: 'history', element: <HistoryPage /> },
      { path: 'history/:id', element: <HistoryDetailPage /> },
      {
        path: 'teaching-assistants',
        element: (
          <RequireInstructor>
            <TeachingAssistantsPage />
          </RequireInstructor>
        ),
      },
      {
        path: 'users',
        element: (
          <RequireAdmin>
            <UsersPage />
          </RequireAdmin>
        ),
      },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ToastProvider>
          <RouterProvider router={router} />
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)
