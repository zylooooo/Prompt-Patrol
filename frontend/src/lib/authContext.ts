import { createContext, useContext } from 'react'
import type { UserRole } from './types'

// Exactly what GET /api/auth/me returns. It does not include the user id yet,
// so anything that needs the id looks the account up by email
export interface Session {
  email: string
  role: UserRole
}

export interface AuthContextValue {
  user: Session | null
  // true while the first /api/auth/me call is still in flight. Guards must wait
  // for this, or a signed-in user gets bounced to the login page on refresh
  loading: boolean
  signOut: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

// Not a credential, just the email Entra should prefill next time
export const LOGIN_HINT_KEY = 'pp_login_hint'

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
