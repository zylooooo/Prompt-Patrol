import { useEffect, useState, type ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { setSignedInEmail } from './api'
import { AuthContext, LOGIN_HINT_KEY, useAuth, type Session } from './authContext'
import { atLeastRole, type UserRole } from './types'

// Sign-in never goes through fetch. /api/auth/login and /api/auth/callback
// answer with redirects to Microsoft, and fetch dies on an opaque redirect,
// so the login page submits a real form and the browser follows the chain.
// All this provider does is ask /api/auth/me who came back
function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    fetch('/api/auth/me', { credentials: 'include' })
      .then((res) => (res.ok ? res.json() : null))
      .then((session: Session | null) => {
        if (cancelled) return
        setUser(session)
        // the mock api layer needs to know who is asking, and it cannot read
        // the session cookie itself
        setSignedInEmail(session?.email ?? null)
        if (session?.email) localStorage.setItem(LOGIN_HINT_KEY, session.email)
      })
      .catch(() => {
        if (!cancelled) setUser(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // logout is a POST that answers with a redirect to Microsoft, so it has to
  // be a real form submission. Fetch would follow the redirect in the
  // background and leave the Microsoft session alive
  function signOut() {
    const form = document.createElement('form')
    form.method = 'post'
    form.action = '/api/auth/logout'
    document.body.appendChild(form)
    form.submit()
  }

  return <AuthContext.Provider value={{ user, loading, signOut }}>{children}</AuthContext.Provider>
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return null
  if (!user) return <Navigate to="/login" replace />
  return children
}

// Roles are ranked like the backend's require_role, so an admin passes an
// instructor check
function RequireRole({ min, children }: { min: UserRole; children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return null
  if (!user || !atLeastRole(user.role, min)) return <Navigate to="/check" replace />
  return children
}

function RequireAdmin({ children }: { children: ReactNode }) {
  return <RequireRole min="root_admin">{children}</RequireRole>
}

function RequireInstructor({ children }: { children: ReactNode }) {
  return <RequireRole min="instructor">{children}</RequireRole>
}

export { AuthProvider, RequireAuth, RequireRole, RequireAdmin, RequireInstructor }
