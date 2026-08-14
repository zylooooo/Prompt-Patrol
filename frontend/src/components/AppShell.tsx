import { useEffect, useRef } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../lib/authContext'
import { atLeastRole, ROLE_TEXT } from '../lib/types'

export default function AppShell() {
  const { user, signOut } = useAuth()
  const location = useLocation()
  const mainRef = useRef<HTMLElement>(null)
  const firstRender = useRef(true)

  // client-side navigation drops focus onto <body>, so move it to the main
  // region where keyboard and screen reader users land on the new content
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false
      return
    }
    mainRef.current?.focus()
  }, [location.pathname])

  // roles are ranked, so an admin gets the instructor entries too
  const navItems = [
    { to: '/check', label: 'Check answers' },
    { to: '/history', label: 'History' },
    ...(user && atLeastRole(user.role, 'instructor')
      ? [{ to: '/teaching-assistants', label: 'Teaching assistants' }]
      : []),
    ...(user && atLeastRole(user.role, 'root_admin') ? [{ to: '/users', label: 'Users' }] : []),
  ]

  return (
    <div className="relative flex min-h-screen bg-bg">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-10 focus:rounded-md focus:bg-surface focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-navy-800"
      >
        Skip to main content
      </a>

      <aside className="flex w-60 shrink-0 flex-col justify-between bg-navy-800 px-6 py-9">
        <div>
          <div className="inline-block">
            <p className="font-display text-lg font-bold text-white">Prompt Patrol</p>
            <div aria-hidden className="mt-2 h-[3px] w-full rounded-full bg-gold-500" />
          </div>

          <nav className="mt-9 flex flex-col gap-1.5" aria-label="Main">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `flex items-center gap-3 rounded-md py-2 text-sm transition-colors ${
                    isActive ? 'font-semibold text-white' : 'text-navy-100/70 hover:text-white'
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <span
                      aria-hidden
                      className={`h-4 w-[3px] rounded-full ${isActive ? 'bg-gold-500' : 'bg-transparent'}`}
                    />
                    {item.label}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        </div>

        <div className="border-t border-white/10 pt-4">
          {/* the session carries email and role only, there is no display name
              until the backend stores one */}
          <p className="text-sm font-semibold break-all text-white">{user?.email}</p>
          <div className="mt-1 flex items-center gap-3 text-[13px]">
            <span className="text-navy-100/60">{user ? ROLE_TEXT[user.role] : ''}</span>
            <button onClick={signOut} className="text-gold-300 transition-colors hover:text-white">
              Sign out
            </button>
          </div>
        </div>
      </aside>

      <main
        id="main-content"
        ref={mainRef}
        tabIndex={-1}
        className="min-w-0 flex-1 px-11 py-11 outline-none"
      >
        <Outlet />
      </main>
    </div>
  )
}
